"""Simulated editing API. Every mutator rejects a protected project identity."""
from pathlib import Path
import secrets
import time

from resolve_mcp.protocol import request,response
from resolve_mcp.transport import safe_path, read_data
from tests.support import LuaBridge

EDIT_API = r'''
local f = fixture
f.protected_project = f.project
f.mutations = {}
f.current = nil
f.project_names = {'테스트_프로젝트','다른_프로젝트'}
local serial = 0
local function id(prefix) serial = serial + 1; return prefix .. serial end
local function mutation(name,p)
    assert(p == f.current and p.uid:match('^new%-project'), 'Attempt to mutate a protected project')
    f.mutations[#f.mutations+1] = name
end
local function new_timeline(p,name)
    local t = {uid=id('timeline-'),name=name,settings={},tracks={video={{}},audio={{}}}}
    t.GetUniqueId=function() return t.uid end
    t.GetName=function() return t.name end
    t.GetStartFrame=function() return t.start_frame or 0 end
    t.GetEndFrame=function() return 900 end
    t.GetTrackCount=function(_,kind) return #t.tracks[kind] end
    t.GetTrackName=function(_,kind,index) return kind .. index end
    t.GetItemListInTrack=function(_,kind,index) return t.tracks[kind][index] end
    t.GetSetting=function(_,name) return t.settings[name] end
    t.SetSetting=function(_,name,value) mutation('SetSetting',p);t.settings[name]=value;return not f.fail_setting end
    t.SetStartTimecode=function() mutation('SetStartTimecode',p);return true end
    t.AddTrack=function(_,kind) mutation('AddTrack',p);t.tracks[kind][#t.tracks[kind]+1]={};return true end
    t.DuplicateTimeline=function(_,name)
        mutation('DuplicateTimeline',p)
        local copy=new_timeline(p,name)
        for key,value in pairs(t.settings) do copy.settings[key]=value end
        for kind,tracks in pairs(t.tracks) do
            copy.tracks[kind]={}
            for i,items in ipairs(tracks) do
                copy.tracks[kind][i]={}
                for _,item in ipairs(items) do table.insert(copy.tracks[kind][i],item) end
            end
        end
        p.timelines[#p.timelines+1]=copy
        return copy
    end
    return t
end
f.manager.GetCurrentProject=function() return f.current end
f.manager.GetProjectListInCurrentFolder=function() return f.project_names end
f.make_bootstrap=function(name)
    -- Reproduce the Windows Resolve empty-list shape in every edit workflow.
    local p={name=name,uid='bootstrap-unique-id',clips={_flags=2097152},folders={_flags=2097152},jobs={_flags=2097152},timelines=0}
    p.GetUniqueId=function() return p.uid end
    p.GetName=function() return p.name end
    p.GetTimelineCount=function() return p.timelines end
    p.GetCurrentTimeline=function() return nil end
    p.GetRenderJobList=function() return p.jobs end
    p.GetMediaPool=function() return {GetRootFolder=function() return {
        GetClipList=function() return p.clips end,GetSubFolderList=function() return p.folders end} end} end
    f.bootstrap=p
    return p
end
f.manager.CloseProject=function(_,p)
    assert(p==f.bootstrap and p==f.current,'Attempt to close protected project')
    f.mutations[#f.mutations+1]='CloseBootstrap'
    if f.fail_close then return false end
    f.current=f.after_close
    return true
end
f.manager.CreateProject=function(_,name)
    assert(not f.current,'Existing project still open')
    local p={uid=id('new-project-'),name=name,timelines={},settings={}}
    f.current=p
    p.GetUniqueId=function() return p.uid end
    p.GetName=function() return p.name end
    p.GetTimelineCount=function() return #p.timelines end
    p.GetTimelineByIndex=function(_,i) return p.timelines[i] end
    p.GetCurrentTimeline=function() return p.current_timeline end
    p.SetCurrentTimeline=function(_,t) mutation('SetCurrentTimeline',p);p.current_timeline=t;return true end
    p.SetSetting=function(_,key,value) mutation('ProjectSetSetting',p);p.settings[key]=value;return true end
    p.GetSetting=function(_,key) return p.settings[key] end
    p.GetCurrentRenderFormatAndCodec=function() return {format='mp4',codec='H264'} end
    local root={name='Master',clips={},children={}}
    local function bind_folder(folder)
        folder.GetName=function() return folder.name end
        folder.GetClipList=function() return folder.clips end
        folder.GetSubFolderList=function() return folder.children end
        return folder
    end
    bind_folder(root)
    local pool={selected=root}
    pool.GetRootFolder=function() return root end
    pool.AddSubFolder=function(_,parent,name)
        mutation('AddSubFolder',p)
        local folder=bind_folder({name=name,clips={},children={}})
        parent.children[#parent.children+1]=folder
        return folder
    end
    pool.SetCurrentFolder=function(_,folder) mutation('SetCurrentFolder',p);pool.selected=folder;return true end
    pool.ImportMedia=function(_,paths)
        mutation('ImportMedia',p)
        local clip={uid=id('media-'),path=paths[1]}
        clip.GetMediaId=function() return clip.uid end
        clip.GetName=function() return '테스트_클립' end
        clip.GetClipProperty=function(_,key)
            local properties={['File Path']=clip.path,FPS=f.media_fps or '30',Frames=f.media_frames or '300'}
            return key and properties[key] or properties
        end
        pool.selected.clips[#pool.selected.clips+1]=clip
        return {clip}
    end
    pool.CreateEmptyTimeline=function(_,name)
        mutation('CreateEmptyTimeline',p)
        local t=new_timeline(p,name);p.timelines[#p.timelines+1]=t;return t
    end
    pool.AppendToTimeline=function(_,infos)
        mutation('AppendToTimeline',p)
        local info=infos[1]
        f.last_append=info
        local duration=info.endFrame-info.startFrame+1
        local item={uid=id('item-')}
        item.GetUniqueId=function() return item.uid end
        item.GetName=function() return info.mediaPoolItem:GetName() end
        item.GetStart=function() return info.recordFrame end
        item.GetEnd=function() return info.recordFrame+duration+(f.bad_append and 1 or 0) end
        item.GetMediaPoolItem=function() return info.mediaPoolItem end
        item.GetLeftOffset=function() return info.startFrame+(f.bad_source and 1 or 0) end
        item.GetRightOffset=function() return tonumber(f.media_frames or '300')-info.endFrame-1 end
        local kind=info.mediaType==1 and 'video' or 'audio'
        local stored=item
        if f.bad_track_media or f.bad_track_source then
            stored={}
            for name,method in pairs(item) do stored[name]=method end
            if f.bad_track_media then stored.GetMediaPoolItem=function() return {GetMediaId=function() return 'wrong-media' end} end end
            if f.bad_track_source then stored.GetLeftOffset=function() return info.startFrame+1 end end
        end
        table.insert(p.current_timeline.tracks[kind][info.trackIndex],stored)
        if f.duplicate_track_item then table.insert(p.current_timeline.tracks[kind][info.trackIndex],stored) end
        if f.fail_append_return then return nil end
        return {item}
    end
    p.GetMediaPool=function() return pool end
    f.project_names[#f.project_names+1]=name
    mutation('CreateProject',p)
    return p
end
f.manager.SaveProject=function() mutation('SaveProject',f.current);return true end
'''


class EditBridge(LuaBridge):
    def __init__(self, mailbox, instance='b'*32):
        super().__init__(mailbox.key,instance)
        self.mailbox=mailbox
        self.lua.globals().fixture=self.api
        self.lua.execute(EDIT_API)
        def read(path):
            target=Path(path.replace('\\','/'))
            try:
                return read_data(target).decode('ascii')
            except FileNotFoundError: return None
        def canonical(path,directory):
            target=safe_path(Path(path))
            assert target.is_dir() if directory else target.is_file() and target.stat().st_nlink == 1
            return str(target).replace('/','\\')
        adapter=self.lua.table_from({'root':str(mailbox.root),'bridge_id':instance,'read':read,
            'canonical_file':lambda path:canonical(path,False),
            'canonical_directory':lambda path:canonical(path,True),'now':time.time,
            'random_hex':lambda:secrets.token_hex(16)})
        self.writable,self.state=self.load('edits.lua').new(self.api.resolve,self.codec,self.crypto,mailbox.key,adapter,self.invoke)
        for name,operation in self.writable.items():self.operations[name]=operation
        self.core=self.core_module.new(self.crypto,self.codec,self.operations,mailbox.key,instance,self.writable)

    def call(self,op,**params):
        rid=secrets.token_hex(16)
        packet=request(self.mailbox.key,rid,self.instance,op,params,5)
        return response(self.mailbox.key,self.process(packet),rid,self.instance)[1]

    def setup_project(self,media):
        self.call('create_test_project')
        bin_id=self.call('create_bin',name='ResolveMCP_TEST_BIN_fixture')['bin_id']
        media_id=self.call('import_media',bin_id=bin_id,path=str(media))['media_id']
        timeline_id=self.call('create_timeline',name='ResolveMCP_TEST_TL_fixture')['timeline_id']
        return {'timeline_id':timeline_id,'media_id':media_id,'media_type':1,'track_index':1,
                'record_frame':10,'source_in':0,'source_out':30}
