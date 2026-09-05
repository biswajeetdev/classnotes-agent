#!/usr/bin/env python3
"""Create the Multi-Output Device (speakers + BlackHole) without Audio MIDI Setup.

    make-multiout.py [--name NAME]

A "Multi-Output Device" is just a *stacked* aggregate device, and CoreAudio can build
one directly -- so the one manual GUI step this pipeline had is not actually manual.
Creating it here means a class is never lost to "the device was never made".

The device is created NON-private, so it persists across reboots and shows up in Audio
MIDI Setup exactly as if it had been made by hand.

Idempotent: if a device with our UID already exists, it reports and exits 0.

Name must NOT contain "BlackHole" -- live-notes.sh refuses to run when the output
device name matches *BlackHole* (that guard exists so you can't sit through a silent
class). It SHOULD contain "Multi-Output" so class-start.sh auto-detects it.
"""
import ctypes
import struct
import sys

ca = ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')
cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

UID = 'com.classnotes.multiout'
NAME = 'Multi-Output (Class Capture)'
BLACKHOLE_MATCH = 'blackhole'


def fourcc(s):
    return struct.unpack('>I', s.encode())[0]


kAudioObjectSystemObject = 1
kAudioHardwarePropertyDevices = fourcc('dev#')
kAudioObjectPropertyScopeGlobal = fourcc('glob')
kAudioObjectPropertyScopeOutput = fourcc('outp')
kAudioDevicePropertyDeviceUID = fourcc('uid ')
kAudioObjectPropertyName = fourcc('lnam')
kAudioDevicePropertyStreams = fourcc('stm#')
kCFStringEncodingUTF8 = 0x08000100


class Addr(ctypes.Structure):
    _fields_ = [('mSelector', ctypes.c_uint32),
                ('mScope', ctypes.c_uint32),
                ('mElement', ctypes.c_uint32)]


ca.AudioObjectGetPropertyDataSize.argtypes = [
    ctypes.c_uint32, ctypes.POINTER(Addr), ctypes.c_uint32,
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32

ca.AudioObjectGetPropertyData.argtypes = [
    ctypes.c_uint32, ctypes.POINTER(Addr), ctypes.c_uint32,
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
ca.AudioObjectGetPropertyData.restype = ctypes.c_int32

ca.AudioHardwareCreateAggregateDevice.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
ca.AudioHardwareCreateAggregateDevice.restype = ctypes.c_int32

cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                  ctypes.c_long, ctypes.c_uint32]
cf.CFStringGetCString.restype = ctypes.c_bool
cf.CFDataCreate.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long]
cf.CFDataCreate.restype = ctypes.c_void_p
cf.CFPropertyListCreateWithData.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
    ctypes.c_void_p, ctypes.c_void_p]
cf.CFPropertyListCreateWithData.restype = ctypes.c_void_p
cf.CFRelease.argtypes = [ctypes.c_void_p]


def cfstr_to_str(ref):
    if not ref:
        return ''
    buf = ctypes.create_string_buffer(2048)
    if cf.CFStringGetCString(ref, buf, 2048, kCFStringEncodingUTF8):
        return buf.value.decode('utf-8', 'replace')
    return ''


def get_cfstring_prop(dev, selector, scope=kAudioObjectPropertyScopeGlobal):
    addr = Addr(selector, scope, 0)
    ref = ctypes.c_void_p()
    size = ctypes.c_uint32(ctypes.sizeof(ref))
    if ca.AudioObjectGetPropertyData(dev, ctypes.byref(addr), 0, None,
                                     ctypes.byref(size), ctypes.byref(ref)) != 0:
        return ''
    s = cfstr_to_str(ref)
    if ref:
        cf.CFRelease(ref)
    return s


def has_output(dev):
    addr = Addr(kAudioDevicePropertyStreams, kAudioObjectPropertyScopeOutput, 0)
    size = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(dev, ctypes.byref(addr), 0, None,
                                         ctypes.byref(size)) != 0:
        return False
    return size.value > 0


def list_devices():
    addr = Addr(kAudioHardwarePropertyDevices, kAudioObjectPropertyScopeGlobal, 0)
    size = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(kAudioObjectSystemObject, ctypes.byref(addr),
                                         0, None, ctypes.byref(size)) != 0:
        sys.exit('error: could not enumerate audio devices')
    n = size.value // ctypes.sizeof(ctypes.c_uint32)
    arr = (ctypes.c_uint32 * n)()
    if ca.AudioObjectGetPropertyData(kAudioObjectSystemObject, ctypes.byref(addr),
                                     0, None, ctypes.byref(size), arr) != 0:
        sys.exit('error: could not read audio device list')
    out = []
    for d in arr:
        out.append({'id': d,
                    'uid': get_cfstring_prop(d, kAudioDevicePropertyDeviceUID),
                    'name': get_cfstring_prop(d, kAudioObjectPropertyName),
                    'output': has_output(d)})
    return out


PLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>name</key><string>{name}</string>
  <key>uid</key><string>{uid}</string>
  <key>stacked</key><integer>1</integer>
  <key>private</key><integer>0</integer>
  <key>master</key><string>{master}</string>
  <key>subdevices</key>
  <array>
    <dict><key>uid</key><string>{master}</string><key>drift</key><integer>0</integer></dict>
    <dict><key>uid</key><string>{bh}</string><key>drift</key><integer>1</integer></dict>
  </array>
</dict>
</plist>
'''


def xml_escape(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def main():
    name = NAME
    if '--name' in sys.argv:
        name = sys.argv[sys.argv.index('--name') + 1]
    if BLACKHOLE_MATCH in name.lower():
        sys.exit('error: name must not contain "BlackHole" — live-notes.sh would '
                 'refuse to run against it')

    devices = list_devices()

    for d in devices:
        if d['uid'] == UID:
            print(f">> already exists: '{d['name']}' — nothing to do")
            return 0

    bh = next((d for d in devices
               if BLACKHOLE_MATCH in d['name'].lower() and d['output']), None)
    if not bh:
        sys.exit('error: BlackHole output device not found. Is the driver loaded? '
                 'Run ~/class-notes/scripts/reload-audio.command or reboot.')

    # The speakers are the master/clock so YOU keep hearing the class at the right
    # rate; BlackHole gets drift compensation because it is the follower.
    spk = next((d for d in devices
                if 'speaker' in d['name'].lower() and d['output']), None)
    if not spk:
        spk = next((d for d in devices if d['output']
                    and BLACKHOLE_MATCH not in d['name'].lower()
                    and 'aggregate' not in d['name'].lower()), None)
    if not spk:
        sys.exit('error: no built-in output device found to pair with BlackHole')

    xml = PLIST.format(name=xml_escape(name), uid=UID,
                       master=xml_escape(spk['uid']), bh=xml_escape(bh['uid']))
    data = xml.encode('utf-8')

    cfdata = cf.CFDataCreate(None, data, len(data))
    plist = cf.CFPropertyListCreateWithData(None, cfdata, 0, None, None)
    if not plist:
        sys.exit('error: could not build the device description')

    new_id = ctypes.c_uint32(0)
    rc = ca.AudioHardwareCreateAggregateDevice(plist, ctypes.byref(new_id))
    cf.CFRelease(plist)
    cf.CFRelease(cfdata)

    if rc != 0:
        sys.exit(f'error: AudioHardwareCreateAggregateDevice failed (status {rc})')

    print(f">> created '{name}'")
    print(f"     master (you hear this): {spk['name']}")
    print(f"     tapped (capture reads): {bh['name']}  [drift compensation on]")
    return 0


if __name__ == '__main__':
    sys.exit(main())
