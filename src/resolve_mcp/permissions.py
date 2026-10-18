"""Owner/SYSTEM ACLs for this application's private directories on Windows."""
import os
from pathlib import Path


def protect_directory(path: Path) -> None:
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [w.LPVOID]
    kernel.LocalFree.restype = w.LPVOID
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    security.ConvertSidToStringSidW.argtypes = [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR,w.DWORD,ctypes.POINTER(w.LPVOID),ctypes.POINTER(w.DWORD)]
    security.SetFileSecurityW.argtypes = [w.LPCWSTR,w.DWORD,w.LPVOID]
    token = w.HANDLE()
    sid_text = w.LPWSTR()
    descriptor = w.LPVOID()
    def checked(value):
        if not value: raise ctypes.WinError(ctypes.get_last_error())
    try:
        checked(security.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)))
        needed = w.DWORD()
        security.GetTokenInformation(token,1,None,0,ctypes.byref(needed))
        if not needed.value: raise ctypes.WinError(ctypes.get_last_error())
        user = ctypes.create_string_buffer(needed.value)
        checked(security.GetTokenInformation(token,1,user,needed,ctypes.byref(needed)))
        sid = ctypes.cast(user,ctypes.POINTER(w.LPVOID))[0]
        checked(security.ConvertSidToStringSidW(sid,ctypes.byref(sid_text)))
        sddl = f'O:{sid_text.value}D:P(A;OICI;FA;;;{sid_text.value})(A;OICI;FA;;;SY)'
        checked(security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,ctypes.byref(descriptor),None))
        checked(security.SetFileSecurityW(str(path),0x80000005,descriptor))
    finally:
        if descriptor: kernel.LocalFree(descriptor)
        if sid_text: kernel.LocalFree(ctypes.cast(sid_text,w.LPVOID))
        if token: kernel.CloseHandle(token)
