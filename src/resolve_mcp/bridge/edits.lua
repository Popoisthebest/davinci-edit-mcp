-- Only a project newly created by this bridge under a local signed approval
-- may be edited. All original projects must be closed before creation.
local M = {}
function M.new(resolve,codec,crypto,key,adapter,invoke)
    local state = {bins={},media={},media_paths={},timelines={}}
    local function deny(message) error('WRITE_DENIED:' .. message) end
    local function approval()
        local packet = adapter.read(adapter.root .. '\\approval.txt')
        if not packet or #packet > 8192 then deny('Local approval required') end
        local fields = {}
        for line in packet:gmatch('([^\n]*)\n') do fields[#fields+1] = line end
        if #fields ~= 6 or table.concat(fields,'\n') .. '\n' ~= packet or fields[1] ~= 'RMC3' then deny('Invalid approval') end
        local body = table.concat(fields,'\n',1,5) .. '\n'
        if not crypto.equal(crypto.hmac(key,body),fields[6]) then deny('Invalid approval signature') end
        local expiry = tonumber(fields[3])
        local now = adapter.now()
        if not expiry or expiry <= now or expiry > now + 3600 then deny('Approval expired') end
        local name,media = crypto.unhex(fields[4]),crypto.unhex(fields[5])
        if #fields[2] ~= 32 or fields[2]:find('[^0-9a-f]') or not name:match('^ResolveMCP_TEST_[%w_%-]+$') or #name > 80 then deny('Invalid test project name') end
        local root_name = media:match('[^/\\]+$')
        if not root_name or not root_name:match('^ResolveMCP_TEST_MEDIA_[%w_%-]+$') then deny('Dedicated test media root required') end
        local marker = adapter.read(media .. '\\.resolve-mcp-test-media')
        local marker_body = 'RMC3\n' .. crypto.hex(media) .. '\n'
        if not marker or not crypto.equal(marker,marker_body .. crypto.hmac(key,marker_body) .. '\n') then deny('Test media marker does not match this session and directory') end
        return {id=fields[2],name=name,media=media}
    end
    local function schema(params,fields)
        for name,value in pairs(params) do
            if fields[name] ~= type(value) then deny('Unknown parameter or wrong type') end
        end
        for name in pairs(fields) do if params[name] == nil then deny('Missing parameter') end end
    end
    local function manager() return invoke(resolve,'GetProjectManager') end
    local function current(grant)
        local p = invoke(manager(),'GetCurrentProject')
        if not state.project or grant.id ~= state.approval or not p then deny('Create a fresh test project in this bridge session') end
        local identified,id = pcall(invoke,p,'GetUniqueId')
        if not identified or id ~= state.project_id or invoke(p,'GetName') ~= grant.name then deny('Current project changed or identity unavailable') end
        return p
    end
    local function pool(p) return invoke(p,'GetMediaPool') end
    local function owned_timeline(p,id,activate)
        local t = state.timelines[id]
        if not t or invoke(t,'GetUniqueId') ~= id then deny('Only a timeline created in this session may be edited') end
        local found = false
        local count = invoke(p,'GetTimelineCount')
        if count > 1000 then deny('Too many timelines to verify ownership') end
        for index = 1,count do
            if invoke(invoke(p,'GetTimelineByIndex',index),'GetUniqueId') == id then found = true end
        end
        if not found then deny('Timeline no longer belongs to the owned test project') end
        if activate ~= false then
            if invoke(p,'SetCurrentTimeline',t) ~= true then error('API_ERROR:Cannot activate test timeline') end
            if invoke(invoke(p,'GetCurrentTimeline'),'GetUniqueId') ~= id then deny('Timeline activation failed') end
        end
        return t
    end
    local function media_path(path,root)
        local ok_file,file = pcall(adapter.canonical_file,path)
        local ok_root,directory = pcall(adapter.canonical_directory,root)
        if not ok_file or not file or not ok_root or not directory
            or file:sub(1,#directory+1):lower() ~= (directory .. '\\'):lower() then deny('Media must be a copied file in the approved test root') end
        local extension = path:match('%.([%a%d]+)$')
        local allowed = {mp4=true,mov=true,mxf=true,mkv=true,wav=true,mp3=true,png=true,jpg=true,jpeg=true}
        if not extension or not allowed[extension:lower()] then deny('Unsupported test media file extension') end
        return file
    end
    local function new_name(name,prefix)
        if not name:match('^' .. prefix .. '[%w_%-]+$') or #name > 100 then deny('Use a distinct test object name') end
    end
    local function integer(value,minimum,maximum)
        if type(value) ~= 'number' or value % 1 ~= 0 or value < minimum or value > maximum then deny('Invalid frame or track index') end
    end
    local function format(t)
        for name,expected in pairs({timelineResolutionWidth=1080,timelineResolutionHeight=1920,timelineFrameRate=30}) do
            if tonumber(invoke(t,'GetSetting',name)) ~= expected then deny('Test timeline format must be 1080x1920 at 30fps') end
        end
        if invoke(t,'GetStartFrame') ~= 0 then deny('Timeline must start at frame zero') end
    end
    local operations = {}
    operations.create_test_project = function(params)
        schema(params,{})
        local grant = approval()
        if state.project or invoke(manager(),'GetCurrentProject') then deny('Close all projects before creating a fresh test project') end
        for _,name in pairs(invoke(manager(),'GetProjectListInCurrentFolder')) do
            if name:lower() == grant.name:lower() then deny('Test project already exists; never reuse it') end
        end
        local p = invoke(manager(),'CreateProject',grant.name)
        if not p then error('API_ERROR:CreateProject failed') end
        state.project,state.project_id,state.approval = p,invoke(p,'GetUniqueId'),grant.id
        if not state.project_id or state.project_id == '' then deny('Project identity unavailable') end
        current(grant)
        if invoke(p,'SetSetting','timelineFrameRate','30') ~= true then error('API_ERROR:Cannot set test project frame rate') end
        return {project_id=state.project_id,name=grant.name,created=true}
    end
    operations.create_bin = function(params)
        schema(params,{name='string'})
        new_name(params.name,'ResolveMCP_TEST_BIN_')
        local p = current(approval())
        local root = invoke(pool(p),'GetRootFolder')
        for _,folder in ipairs(invoke(root,'GetSubFolderList')) do
            if invoke(folder,'GetName') == params.name then deny('Bin already exists') end
        end
        local folder = invoke(pool(p),'AddSubFolder',root,params.name)
        if not folder then error('API_ERROR:Cannot create bin') end
        local id = adapter.random_hex()
        state.bins[id] = folder
        return {bin_id=id,name=params.name}
    end
    operations.import_media = function(params)
        schema(params,{bin_id='string',path='string'})
        local grant = approval()
        local p = current(grant)
        local folder = state.bins[params.bin_id]
        if not folder then deny('Only a bin created in this session is allowed') end
        local path = media_path(params.path,grant.media)
        if invoke(pool(p),'SetCurrentFolder',folder) ~= true then error('API_ERROR:Cannot select test bin') end
        local clips = invoke(pool(p),'ImportMedia',{params.path})
        if type(clips) ~= 'table' or #clips ~= 1 then error('API_ERROR:ImportMedia did not return one clip') end
        local clip = clips[1]
        local actual = adapter.canonical_file(invoke(clip,'GetClipProperty','File Path'))
        if not actual or actual:lower() ~= path:lower() then error('API_ERROR:Imported media readback mismatch') end
        local id = invoke(clip,'GetMediaId')
        if type(id) ~= 'string' or id == '' then error('API_ERROR:Media identity unavailable') end
        state.media[id] = clip
        state.media_paths[id] = path
        return {media_id=id,name=invoke(clip,'GetName')}
    end
    operations.create_timeline = function(params)
        schema(params,{name='string'})
        new_name(params.name,'ResolveMCP_TEST_TL_')
        local p = current(approval())
        for i = 1,invoke(p,'GetTimelineCount') do
            if invoke(invoke(p,'GetTimelineByIndex',i),'GetName') == params.name then deny('Timeline already exists') end
        end
        local t = invoke(pool(p),'CreateEmptyTimeline',params.name)
        if not t then error('API_ERROR:Cannot create timeline') end
        local id = invoke(t,'GetUniqueId')
        if type(id) ~= 'string' or id == '' then error('API_ERROR:Timeline identity unavailable') end
        state.timelines[id] = t
        owned_timeline(p,id)
        for _,setting in ipairs({{'useCustomSettings','1'},{'timelineResolutionWidth','1080'},{'timelineResolutionHeight','1920'},{'timelineFrameRate','30'}}) do
            if invoke(t,'SetSetting',setting[1],setting[2]) ~= true then error('API_ERROR:Cannot configure test timeline') end
        end
        if invoke(t,'SetStartTimecode','00:00:00:00') ~= true then error('API_ERROR:Cannot set frame-zero origin') end
        format(t)
        if invoke(t,'GetStartFrame') ~= 0 then deny('Timeline must start at frame zero') end
        return {timeline_id=id,name=params.name,width=1080,height=1920,fps=30}
    end
    operations.duplicate_timeline = function(params)
        schema(params,{timeline_id='string',name='string'})
        new_name(params.name,'ResolveMCP_TEST_TL_')
        local p = current(approval())
        local source = owned_timeline(p,params.timeline_id)
        for i = 1,invoke(p,'GetTimelineCount') do
            if invoke(invoke(p,'GetTimelineByIndex',i),'GetName') == params.name then deny('Timeline already exists') end
        end
        local duplicate = invoke(source,'DuplicateTimeline',params.name)
        if not duplicate then error('API_ERROR:Cannot duplicate test timeline') end
        local id = invoke(duplicate,'GetUniqueId')
        if type(id) ~= 'string' or id == '' or state.timelines[id] then error('API_ERROR:Invalid duplicate identity') end
        state.timelines[id] = duplicate
        format(duplicate)
        return {timeline_id=id,name=params.name}
    end
    operations.add_track = function(params)
        schema(params,{timeline_id='string',track_type='string'})
        if params.track_type ~= 'video' and params.track_type ~= 'audio' then deny('Invalid track type') end
        local t = owned_timeline(current(approval()),params.timeline_id)
        local count = invoke(t,'GetTrackCount',params.track_type)
        if count >= 16 then deny('Test track limit reached') end
        local ok
        if params.track_type == 'audio' then ok = invoke(t,'AddTrack','audio','stereo')
        else ok = invoke(t,'AddTrack','video') end
        if ok ~= true or invoke(t,'GetTrackCount',params.track_type) ~= count + 1 then error('API_ERROR:Track readback mismatch') end
        return {track_type=params.track_type,track_index=count+1}
    end
    local function plan(params)
        schema(params,{timeline_id='string',media_id='string',media_type='number',track_index='number',record_frame='number',source_in='number',source_out='number'})
        integer(params.media_type,1,2);integer(params.track_index,1,16)
        integer(params.record_frame,0,2147483647);integer(params.source_in,0,2147483647);integer(params.source_out,1,2147483647)
        if params.source_out <= params.source_in then deny('Use a nonempty half-open source range') end
        local grant = approval()
        local p = current(grant)
        -- Read-only planning must not switch the current timeline.
        local t,clip = owned_timeline(p,params.timeline_id,false),state.media[params.media_id]
        if not clip or invoke(clip,'GetMediaId') ~= params.media_id then deny('Use media imported in this session') end
        local path = media_path(invoke(clip,'GetClipProperty','File Path'),grant.media)
        if path:lower() ~= state.media_paths[params.media_id]:lower() then deny('Imported test media was relinked') end
        format(t)
        local fps,frames = tonumber(invoke(clip,'GetClipProperty','FPS')),tonumber(invoke(clip,'GetClipProperty','Frames'))
        integer(frames,1,2147483647)
        if fps ~= 30 or params.source_out > frames then deny('Only exact 30fps media with a valid source frame count is supported') end
        local kind = params.media_type == 1 and 'video' or 'audio'
        if params.track_index > invoke(t,'GetTrackCount',kind) then deny('Track does not exist; add it explicitly') end
        local duration = params.source_out - params.source_in
        if params.record_frame + duration > 2147483647 then deny('Timeline frame limit exceeded') end
        for _,item in ipairs(invoke(t,'GetItemListInTrack',kind,params.track_index)) do
            if params.record_frame < invoke(item,'GetEnd') and params.record_frame + duration > invoke(item,'GetStart') then deny('Placement overlaps an existing clip') end
        end
        return p,t,clip,kind,duration,frames
    end
    operations.plan_append = function(params)
        local _,_,_,kind,duration = plan(params)
        return {dry_run=true,track_type=kind,record_frame=params.record_frame,duration_frames=duration,source_end_inclusive=params.source_out-1}
    end
    operations.append_clip = function(params)
        local p,t,clip,kind,duration,source_frames = plan(params)
        owned_timeline(p,params.timeline_id)
        local items = invoke(pool(p),'AppendToTimeline',{{mediaPoolItem=clip,startFrame=params.source_in,endFrame=params.source_out-1,
            mediaType=params.media_type,trackIndex=params.track_index,recordFrame=params.record_frame}})
        if type(items) ~= 'table' or #items ~= 1 then error('API_ERROR:Append did not return one item; inspect before retrying') end
        local item = items[1]
        if invoke(item,'GetStart') ~= params.record_frame or invoke(item,'GetEnd') ~= params.record_frame + duration
            or invoke(invoke(item,'GetMediaPoolItem'),'GetMediaId') ~= params.media_id
            or invoke(item,'GetLeftOffset') ~= params.source_in
            or invoke(item,'GetRightOffset') ~= source_frames - params.source_out then error('API_ERROR:Placement or source trim readback mismatch; inspect before retrying') end
        local found = 0
        for _,present in ipairs(invoke(t,'GetItemListInTrack',kind,params.track_index)) do
            if invoke(present,'GetStart') == params.record_frame and invoke(present,'GetEnd') == params.record_frame + duration
                and invoke(invoke(present,'GetMediaPoolItem'),'GetMediaId') == params.media_id
                and invoke(present,'GetLeftOffset') == params.source_in
                and invoke(present,'GetRightOffset') == source_frames - params.source_out then found = found + 1 end
        end
        if found ~= 1 then error('API_ERROR:Target track media or source readback mismatch') end
        return {timeline_id=params.timeline_id,track_type=kind,track_index=params.track_index,start_frame=params.record_frame,end_frame=params.record_frame+duration,
            duration_frames=duration,source_in=params.source_in,source_out=params.source_out}
    end
    operations.save_test_project = function(params)
        schema(params,{})
        current(approval())
        if invoke(manager(),'SaveProject') ~= true then error('API_ERROR:Cannot save test project') end
        return {saved=true,project_id=state.project_id}
    end
    return operations,state
end
return M
