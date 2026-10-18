"""Real LuaJIT protocol/handlers with explicitly simulated Resolve objects."""

from pathlib import Path
import threading
import time

from lupa.luajit21 import LuaRuntime

from resolve_mcp.transport import atomic_write, read_data
from resolve_mcp.bundle import loader_source

BRIDGE = Path(__file__).resolve().parents[1] / 'src/resolve_mcp/bridge'


def restricted_loader(lua):
    # Only the test harness uses the LuaJIT package system to inject host globals.
    # Every production module then runs with the same omissions as Resolve.
    lua.globals().ffi=lua.eval("require('ffi')")
    lua.globals().bit=lua.eval("require('bit')")
    lua.execute('require=nil; package=nil; io=nil; debug=nil; loadfile=nil; dofile=nil')
    return lua.execute(loader_source()+'\nreturn module')

FAKE_RESOLVE = r'''
local item = {GetName=function() return '클립' end,GetStart=function() return 10 end,GetEnd=function() return 40 end}
local timeline = {
    GetName=function() return '테스트_타임라인' end,
    GetTrackCount=function(_,kind) return kind == 'video' and 4 or 3 end,
    GetStartFrame=function() return 0 end,GetEndFrame=function() return 900 end,
    GetTrackName=function(_,kind,index) return kind .. index end,
    GetItemListInTrack=function(_,kind,index) return index == 1 and {item} or {} end,
}
local clip = {GetMediaId=function() return 'media-1' end,GetName=function() return '클립' end,
    GetClipProperty=function() return {['File Path']='C:\\fixtures\\clip.mp4',FPS='30',Frames='90'} end}
local folder = {GetName=function() return 'Master' end,GetClipList=function() return {clip} end,
    GetSubFolderList=function() return {} end}
local pool = {GetRootFolder=function() return folder end}
local project = {
    GetName=function() return '테스트_프로젝트' end,GetTimelineCount=function() return 1 end,
    GetCurrentTimeline=function() return timeline end,GetTimelineByIndex=function() return timeline end,
    GetMediaPool=function() return pool end,GetSetting=function(_,name) return name == 'timelineFrameRate' and '30' or '1080' end,
    GetCurrentRenderFormatAndCodec=function() return {format='mp4',codec='H264'} end,
}
local manager = {GetCurrentProject=function() return project end,
    GetProjectListInCurrentFolder=function() return {'테스트_프로젝트','다른_프로젝트'} end}
return {resolve={GetVersionString=function() return '21.1.1 MOCK' end,GetProjectManager=function() return manager end},
    project=project,timeline=timeline,pool=pool,folder=folder,clip=clip,manager=manager}
'''


class LuaBridge:
    def __init__(self, key: bytes, instance='b' * 32):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.modules = restricted_loader(self.lua)
        self.crypto = self.load('crypto.lua')
        self.codec = self.load('codec.lua')
        self.api = self.lua.execute(FAKE_RESOLVE)
        self.lua.globals().fixture = self.api
        self.operations, self.invoke = self.load('reads.lua').new(self.api.resolve, self.codec)
        self.core_module = self.load('core.lua')
        self.core = self.core_module.new(self.crypto, self.codec, self.operations, key, instance)
        self.instance = instance

    def load(self, filename):
        name = 'bridge' if filename == 'ResolveMCP3.lua' else filename.removesuffix('.lua')
        return self.modules(name)

    def process(self, packet: bytes, now=None):
        result = self.core.process(self.core, packet, time.time() if now is None else now)
        return result.encode('ascii') if result is not None else None


class FileBridge:
    def __init__(self, mailbox, instance='b' * 32, delay=0, factory=None):
        self.mailbox, self.instance, self.delay = mailbox, instance, delay
        self.factory = factory
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.errors = []
        self.requests = []

    def __enter__(self):
        def run():
            try:
                bridge = self.factory(self.mailbox,self.instance) if self.factory else LuaBridge(self.mailbox.key, self.instance)
                self.ready.set()
                previous = None
                while not self.stop.is_set():
                    try:
                        packet = read_data(self.mailbox.root / 'request.txt')
                    except FileNotFoundError:
                        packet = None
                    if packet and packet != previous:
                        self.requests.append(packet)
                        if self.stop.wait(self.delay):
                            break
                        result = bridge.process(packet)
                        if result is not None:
                            atomic_write(self.mailbox.root / 'response.txt', result)
                        previous = packet
                        if bridge.core.stopped:
                            break
                    self.stop.wait(0.002)
            except BaseException as error:
                self.errors.append(error)
                self.ready.set()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert self.ready.wait(5), 'Bridge worker did not start'
        if self.errors:
            raise self.errors[0]
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(5)
        assert not self.thread.is_alive(), 'Bridge worker did not stop'
        if self.errors:
            raise self.errors[0]
