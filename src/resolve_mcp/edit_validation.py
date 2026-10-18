"""One approved fresh-project video-edit validation; no retries or cleanup edits."""
import base64
import hashlib
import json
import os
from pathlib import Path
import uuid

from .bundle import console_bundle, lua_string, utility_launcher
from .editing import Editor, approve, approve_bootstrap, prepare_media_root
from .permissions import protect_directory
from .protocol import BridgeError
from .transport import atomic_write, read_data, safe_path

FIXTURE_SHA256='84a2f1bbde10373002bccb8cf46d88738407ddc16385311acbc29d0df5e5aa10'


def prepare_validation() -> dict:
    if os.name!='nt' or not os.environ.get('LOCALAPPDATA') or not os.environ.get('APPDATA'):
        raise RuntimeError('Prepare the edit validation on Windows')
    identifier=uuid.uuid4().hex
    root=safe_path(Path(os.environ['LOCALAPPDATA'])/('ResolveMCPEdit_'+identifier))
    root.mkdir(mode=0o700);protect_directory(root)
    editor=Editor(root/'mailbox',timeout=29)
    media=root/('ResolveMCP_TEST_MEDIA_'+identifier[:12])
    prepare_media_root(editor,media)
    fixture=base64.b64decode((Path(__file__).parent/'fixtures'/'portrait30.mp4.b64').read_bytes())
    if hashlib.sha256(fixture).hexdigest()!=FIXTURE_SHA256:raise ValueError('Synthetic fixture integrity failure')
    atomic_write(media/'fixture.mp4',fixture)
    payload=root/'EditService.lua'
    payload.write_text(console_bundle(editor.root,enable_edits=True),encoding='utf-8',newline='\n')
    menu=safe_path(Path(os.environ['APPDATA'])/'Blackmagic Design'/'DaVinci Resolve'/'Support'/'Fusion'/'Scripts'/'Utility'/
        f'ResolveMCP_Edit_{identifier[:8]}.lua')
    menu.parent.mkdir(parents=True,exist_ok=True)
    with menu.open('x',encoding='ascii',newline='\n') as stream:stream.write(utility_launcher(payload,identifier,startup_seconds=600))
    info={'edit_validation_format':2,'run_id':identifier,'root':str(root),'mailbox':str(editor.root),
        'bootstrap_project_name':'ResolveMCP_BOOT_'+identifier,
        'project_name':'ResolveMCP_TEST_probe_'+identifier[:12],'media_root':str(media),
        'fixture':str(media/'fixture.mp4'),'fixture_sha256':FIXTURE_SHA256,
        'service_script':str(payload),'service_sha256':hashlib.sha256(payload.read_bytes()).hexdigest(),
        'utility_menu_script':str(menu),'utility_sha256':hashlib.sha256(menu.read_bytes()).hexdigest(),
        'console_command':'RMCEdit = dofile('+lua_string(str(payload))+'); RMCEdit.run(180,"Console",600)',
        'result_file':str(root/'edit-result.json'),'editing_test':'NOT_RUN'}
    atomic_write(root/'edit-info.json',json.dumps(info,ensure_ascii=True,indent=2).encode('ascii'))
    return info


def load_validation(info_path: Path) -> dict:
    info_path=safe_path(info_path);info=json.loads(read_data(info_path).decode('ascii'))
    identifier=info.get('run_id','')
    if info.get('edit_validation_format')!=2 or len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('Invalid edit validation manifest')
    root=safe_path(Path(info['root']))
    if root!=info_path.parent or root.name!='ResolveMCPEdit_'+identifier:raise ValueError('Invalid validation root')
    expected={'mailbox':root/'mailbox','media_root':root/('ResolveMCP_TEST_MEDIA_'+identifier[:12]),
        'service_script':root/'EditService.lua','result_file':root/'edit-result.json'}
    for name,path in expected.items():
        if safe_path(Path(info[name]))!=path:raise ValueError('Validation path mismatch: '+name)
    if info['project_name']!='ResolveMCP_TEST_probe_'+identifier[:12] or Path(info['fixture'])!=expected['media_root']/'fixture.mp4':
        raise ValueError('Unexpected validation target')
    if info.get('bootstrap_project_name')!='ResolveMCP_BOOT_'+identifier:raise ValueError('Unexpected bootstrap project')
    if not (expected['mailbox']/'session.key').is_file():raise ValueError('Prepared key missing; do not recreate')
    for path,digest in [(Path(info['fixture']),FIXTURE_SHA256),(expected['service_script'],info['service_sha256'])]:
        if hashlib.sha256(read_data(safe_path(path))).hexdigest()!=digest:raise ValueError('Validation source/fixture integrity mismatch')
    return info


def run_validation(info_path: Path, confirmation: str, bootstrap_confirmation: str, *, editor_factory=Editor, startup_timeout=600) -> dict:
    info=load_validation(info_path)
    if confirmation!=info['project_name']:raise BridgeError('WRITE_DENIED','Confirm the exact new test project name')
    if bootstrap_confirmation!=info['bootstrap_project_name']:
        raise BridgeError('WRITE_DENIED','Confirm the exact new empty bootstrap project name')
    root=Path(info['root'])
    # Never resume an outcome that may already have created/imported/appended.
    with (root/'started.json').open('x',encoding='ascii') as stream:json.dump({'run_id':info['run_id']},stream)
    editor=editor_factory(Path(info['mailbox']),timeout=29)
    report={'run_id':info['run_id'],'project_name':info['project_name'],'editing_test':'NOT_RUN',
        'bootstrap_project_name':info['bootstrap_project_name'],'result':'WAITING_FOR_SERVICE',
        'stages':[],'may_have_changes':False,'automatic_retry':False}
    current_stage='WAIT_FOR_SERVICE'
    def persist():atomic_write(root/'edit-result.json',json.dumps(report,ensure_ascii=True,indent=2).encode('ascii'))
    def call(op,**params):
        nonlocal current_stage
        current_stage=op;report['last_stage']=op;persist()
        data=editor.call(op,**params)
        report['stages'].append({'operation':op,'status':'PASS'})
        persist();return data
    try:
        report['last_stage']=current_stage;persist()
        editor.wait_ready(startup_timeout)
        current_stage='LOCAL_APPROVAL'
        grant=approve(editor,info['project_name'],Path(info['media_root']),confirmation,minutes=15)
        project_context=call('current_project')
        current_stage='BOOTSTRAP_APPROVAL'
        approve_bootstrap(editor,grant,bootstrap_confirmation,project_context)
        report['bootstrap_project_id']=project_context['project_id']
        report['result']='RUNNING';report['editing_test']='RUNNING'
        report['may_have_changes']=True
        project=call('create_test_project')
        bin_id=call('create_bin',name='ResolveMCP_TEST_BIN_'+info['run_id'][:12])['bin_id']
        media_id=call('import_media',bin_id=bin_id,path=info['fixture'])['media_id']
        timeline=call('create_timeline',name='ResolveMCP_TEST_TL_'+info['run_id'][:12])
        params={'timeline_id':timeline['timeline_id'],'media_id':media_id,'media_type':1,
            'track_index':1,'record_frame':0,'source_in':3,'source_out':63}
        call('plan_append',**params)
        placement=call('append_clip',**params)
        readback=call('timeline_items')
        own_project=call('current_project')
        current_stage='VERIFY_READBACK';report['last_stage']=current_stage
        items=[item for track in readback.get('tracks',[]) if track['type']=='video' and track['index']==1 for item in track['items']]
        expected=(media_id,0,60,3,27)
        actual=[(item.get('media_id'),item.get('start_frame'),item.get('end_frame'),item.get('left_offset_frames'),item.get('right_offset_frames')) for item in items]
        if (actual!=[expected] or readback.get('timeline_id')!=timeline['timeline_id'] or
            own_project.get('project_id')!=project['project_id'] or own_project.get('name')!=info['project_name'] or
            (timeline.get('width'),timeline.get('height'),timeline.get('fps'))!=(1080,1920,30)):
            raise BridgeError('READBACK_MISMATCH','Do not retry; inspect the new test project')
        report['verified']={'project_id':project['project_id'],'timeline_id':timeline['timeline_id'],
            'width':1080,'height':1920,'fps':30,'video_items':1,'start_frame':0,'end_frame':60,
            'source_in':3,'source_out':63,'media_id':media_id}
        call('save_test_project')
        report['editing_test']='PASS';report['result']='PASS'
    except Exception as error:
        report['result']='FAIL'
        if report['editing_test']=='RUNNING':report['editing_test']='FAIL'
        report['failed_stage']=current_stage
        report['error_code']=error.code if isinstance(error,BridgeError) else type(error).__name__
        report['error']=str(error)[:300]
    finally:
        # Revoke first, even on timeout. A call already in progress cannot be
        # cancelled. Stop is lifecycle only; no edit is automatically retried.
        safe_path(editor.root/'approval.txt').unlink(missing_ok=True)
        safe_path(editor.root/'bootstrap-approval.txt').unlink(missing_ok=True)
        if editor.bridge_id is not None:
            try:editor.call('stop');report['service_stop']='PASS'
            except Exception:report['service_stop']='UNCONFIRMED'
        persist()
    return report
