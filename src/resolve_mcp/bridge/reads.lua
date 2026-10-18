local M = {}
function M.new(resolve, codec)
    local function invoke(object, name, ...)
        if not object or type(object[name]) ~= 'function' then error('UNSUPPORTED_API:' .. name) end
        return object[name](object, ...)
    end
    local function project() return invoke(invoke(resolve, 'GetProjectManager'), 'GetCurrentProject') end
    local function timeline()
        local p = project()
        return p and invoke(p, 'GetCurrentTimeline') or nil
    end
    -- Optional metadata must not break the v0.2 read-only baseline on hosts
    -- lacking a newer API. Report unavailable fields instead of inventing IDs.
    local function optional(info, field, object, method, ...)
        local ok,value = pcall(invoke,object,method,...)
        if ok and value ~= nil and value ~= '' then
            info[field] = value
            return value
        end
        info.unavailable_fields = info.unavailable_fields or codec.array()
        info.unavailable_fields[#info.unavailable_fields+1] = field
    end
    local function project_info(p)
        if not p then return {project_open=false} end
        local info = {project_open=true,name=invoke(p,'GetName'),timeline_count=invoke(p,'GetTimelineCount')}
        optional(info,'project_id',p,'GetUniqueId')
        return info
    end
    local function timeline_info(t)
        if not t then return {timeline_open=false} end
        local info = {timeline_open=true,name=invoke(t,'GetName'),video_tracks=invoke(t,'GetTrackCount','video'),
            audio_tracks=invoke(t,'GetTrackCount','audio'),start_frame=invoke(t,'GetStartFrame'),end_frame=invoke(t,'GetEndFrame')}
        optional(info,'timeline_id',t,'GetUniqueId')
        return info
    end
    local operations = {}
    operations.ping = function()
        return {connected=true,resolve_version=invoke(resolve,'GetVersionString'),protocol=3,version='0.3.0',
            writes_enabled=false,capabilities=codec.array({'current_project','current_timeline','projects','timelines','tracks','media_pool','render_settings','timeline_items'})}
    end
    operations.current_project = function() return project_info(project()) end
    operations.current_timeline = function() return timeline_info(timeline()) end
    operations.projects = function()
        local names = invoke(invoke(resolve,'GetProjectManager'),'GetProjectListInCurrentFolder')
        assert(type(names) == 'table', 'Invalid project list')
        local output = codec.array()
        for _,name in pairs(names) do output[#output+1] = name end
        table.sort(output)
        return {projects=output}
    end
    operations.timelines = function()
        local p, output = project(), codec.array()
        if not p then return {project_open=false,timelines=output} end
        local count = invoke(p,'GetTimelineCount')
        assert(count <= 1000, 'Result limit exceeded')
        for index = 1,count do
            local info = timeline_info(invoke(p,'GetTimelineByIndex',index))
            info.index = index
            output[#output+1] = info
        end
        return {project_open=true,timelines=output}
    end
    local function tracks(include_items)
        local t, output = timeline(), codec.array()
        if not t then return {timeline_open=false,tracks=output} end
        for _,kind in ipairs({'video','audio'}) do
            local count = invoke(t,'GetTrackCount',kind)
            assert(count <= 1000, 'Result limit exceeded')
            for index = 1,count do
                local items = invoke(t,'GetItemListInTrack',kind,index)
                assert(type(items) == 'table' and #items <= 1000, 'Invalid item list')
                local info = {type=kind,index=index,name=invoke(t,'GetTrackName',kind,index),item_count=#items}
                if include_items then
                    info.items = codec.array()
                    for _,item in ipairs(items) do
                        local row = {name=invoke(item,'GetName'),start_frame=invoke(item,'GetStart'),end_frame=invoke(item,'GetEnd')}
                        optional(row,'item_id',item,'GetUniqueId')
                        optional(row,'left_offset_frames',item,'GetLeftOffset')
                        optional(row,'right_offset_frames',item,'GetRightOffset')
                        local ok,media = pcall(invoke,item,'GetMediaPoolItem')
                        optional(row,'media_id',ok and media or nil,'GetMediaId')
                        -- Raw source offsets are useful even for audio, generators
                        -- or retimed clips; do not infer an unverified source FPS.
                        info.items[#info.items+1] = row
                    end
                end
                output[#output+1] = info
            end
        end
        local result = {timeline_open=true,tracks=output}
        optional(result,'timeline_id',t,'GetUniqueId')
        return result
    end
    operations.tracks = function() return tracks(false) end
    operations.timeline_items = function() return tracks(true) end
    operations.media_pool = function()
        local p, output, seen, total = project(), codec.array(), {}, 0
        if not p then return {project_open=false,bins=output} end
        local function walk(folder, parent, depth)
            assert(depth <= 16 and not seen[folder], 'Invalid bin graph')
            seen[folder] = true
            total = total + 1
            assert(total <= 1000, 'Result limit exceeded')
            local path = parent .. '/' .. invoke(folder,'GetName')
            local clips = codec.array()
            for _,clip in ipairs(invoke(folder,'GetClipList')) do
                total = total + 1
                assert(total <= 1000, 'Result limit exceeded')
                clips[#clips+1] = {id=invoke(clip,'GetMediaId'),name=invoke(clip,'GetName'),properties=invoke(clip,'GetClipProperty')}
            end
            output[#output+1] = {path=path,clips=clips}
            for _,child in ipairs(invoke(folder,'GetSubFolderList')) do walk(child,path,depth+1) end
        end
        walk(invoke(invoke(p,'GetMediaPool'),'GetRootFolder'),'',0)
        return {project_open=true,bins=output}
    end
    operations.render_settings = function()
        local p = project()
        if not p then return {project_open=false} end
        local settings = {}
        for _,key in ipairs({'timelineResolutionWidth','timelineResolutionHeight','timelineFrameRate'}) do
            settings[key] = invoke(p,'GetSetting',key)
        end
        return {project_open=true,timeline_settings=settings,format_and_codec=invoke(p,'GetCurrentRenderFormatAndCodec')}
    end
    return operations, invoke
end
return M
