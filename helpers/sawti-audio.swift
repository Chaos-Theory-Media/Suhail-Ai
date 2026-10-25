// sawti-audio — small CoreAudio helper for Sawti. Compiled on the Mac by INSTALL_SAWTI.command.
//
// Commands (all print one JSON object):
//   list
//   create --name N --uid U --main MAINUID --sub UID [--sub UID ...] [--stacked]
//   destroy --uid U            (only devices whose UID starts with com.imi.sawti.)
//   set-rate --uid U --rate 48000
//   set-default --role input|output|system --uid U
//
// It never reads, records or changes audio content; it only lists and configures devices.
import CoreAudio
import Foundation

struct Failure: Error { let message: String }

let systemObject = AudioObjectID(kAudioObjectSystemObject)

func address(_ selector: AudioObjectPropertySelector,
             _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    return AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
}

func deviceIDs() -> [AudioObjectID] {
    var a = address(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(systemObject, &a, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(systemObject, &a, 0, nil, &size, &ids) == noErr else { return [] }
    return ids
}

func stringProperty(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String {
    var a = address(selector)
    var value: Unmanaged<CFString>? = nil
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    let status = withUnsafeMutablePointer(to: &value) { ptr in
        AudioObjectGetPropertyData(id, &a, 0, nil, &size, ptr)
    }
    guard status == noErr, let v = value else { return "" }
    return v.takeRetainedValue() as String
}

func uint32Property(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> UInt32 {
    var a = address(selector)
    var value: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    return AudioObjectGetPropertyData(id, &a, 0, nil, &size, &value) == noErr ? value : 0
}

func sampleRate(_ id: AudioObjectID) -> Double {
    var a = address(kAudioDevicePropertyNominalSampleRate)
    var value: Float64 = 0
    var size = UInt32(MemoryLayout<Float64>.size)
    return AudioObjectGetPropertyData(id, &a, 0, nil, &size, &value) == noErr ? value : 0
}

func availableRates(_ id: AudioObjectID) -> [Double] {
    var a = address(kAudioDevicePropertyAvailableNominalSampleRates)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(id, &a, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ranges = [AudioValueRange](repeating: AudioValueRange(mMinimum: 0, mMaximum: 0),
                                   count: Int(size) / MemoryLayout<AudioValueRange>.size)
    guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, &ranges) == noErr else { return [] }
    return ranges.map { $0.mMinimum }
}

func channelCount(_ id: AudioObjectID, input: Bool) -> Int {
    var a = address(kAudioDevicePropertyStreamConfiguration,
                    input ? kAudioDevicePropertyScopeInput : kAudioDevicePropertyScopeOutput)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(id, &a, 0, nil, &size) == noErr, size > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, raw) == noErr else { return 0 }
    let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    var total = 0
    for buffer in list { total += Int(buffer.mNumberChannels) }
    return total
}

func subDeviceUIDs(_ id: AudioObjectID) -> [String] {
    var a = address(kAudioAggregateDevicePropertyFullSubDeviceList)
    var value: Unmanaged<CFArray>? = nil
    var size = UInt32(MemoryLayout<Unmanaged<CFArray>?>.size)
    let status = withUnsafeMutablePointer(to: &value) { ptr in
        AudioObjectGetPropertyData(id, &a, 0, nil, &size, ptr)
    }
    guard status == noErr, let v = value else { return [] }
    let array = v.takeRetainedValue() as NSArray
    return array.compactMap { $0 as? String }
}

func defaultDevice(_ selector: AudioObjectPropertySelector) -> AudioObjectID {
    var a = address(selector)
    var value = AudioObjectID(0)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    _ = AudioObjectGetPropertyData(systemObject, &a, 0, nil, &size, &value)
    return value
}

func transportName(_ t: UInt32) -> String {
    if t == kAudioDeviceTransportTypeAggregate { return "aggregate" }
    if t == kAudioDeviceTransportTypeVirtual { return "virtual" }
    if t == kAudioDeviceTransportTypeUSB { return "usb" }
    if t == kAudioDeviceTransportTypeBuiltIn { return "builtin" }
    if t == kAudioDeviceTransportTypeThunderbolt { return "thunderbolt" }
    if t == kAudioDeviceTransportTypeBluetooth || t == kAudioDeviceTransportTypeBluetoothLE { return "bluetooth" }
    return "other"
}

func findDevice(uid: String) -> AudioObjectID? {
    return deviceIDs().first { stringProperty($0, kAudioDevicePropertyDeviceUID) == uid }
}

func listDevices() -> [String: Any] {
    let defIn = defaultDevice(kAudioHardwarePropertyDefaultInputDevice)
    let defOut = defaultDevice(kAudioHardwarePropertyDefaultOutputDevice)
    let defSys = defaultDevice(kAudioHardwarePropertyDefaultSystemOutputDevice)
    var devices: [[String: Any]] = []
    for id in deviceIDs() {
        let transport = transportName(uint32Property(id, kAudioDevicePropertyTransportType))
        devices.append([
            "id": Int(id),
            "uid": stringProperty(id, kAudioDevicePropertyDeviceUID),
            "name": stringProperty(id, kAudioObjectPropertyName),
            "manufacturer": stringProperty(id, kAudioObjectPropertyManufacturer),
            "transport": transport,
            "inputs": channelCount(id, input: true),
            "outputs": channelCount(id, input: false),
            "rate": sampleRate(id),
            "rates": availableRates(id),
            "subdevices": transport == "aggregate" ? subDeviceUIDs(id) : [],
            "default_input": id == defIn,
            "default_output": id == defOut,
            "default_system": id == defSys,
        ])
    }
    return ["ok": true, "devices": devices]
}

func createAggregate(name: String, uid: String, main: String, subs: [String], stacked: Bool) throws -> [String: Any] {
    if let existing = findDevice(uid: uid) {
        return ["ok": true, "id": Int(existing), "existed": true]
    }
    for s in subs where findDevice(uid: s) == nil {
        throw Failure(message: "Sub-device not found: \(s)")
    }
    let subList: [[String: Any]] = subs.map { ["uid": $0, "drift": $0 == main ? 0 : 1] }
    let description: [String: Any] = [
        "name": name, "uid": uid, "private": 0, "stacked": stacked ? 1 : 0,
        "master": main, "clock": main, "subdevices": subList,
    ]
    var newID = AudioObjectID(0)
    let status = AudioHardwareCreateAggregateDevice(description as CFDictionary, &newID)
    if status != noErr { throw Failure(message: "CoreAudio refused to create \(name) (status \(status))") }
    // Give coreaudiod a moment to publish the new device before anyone queries it.
    _ = CFRunLoopRunInMode(CFRunLoopMode.defaultMode, 0.5, false)
    return ["ok": true, "id": Int(newID), "existed": false]
}

func destroy(uid: String) throws -> [String: Any] {
    guard uid.hasPrefix("com.imi.sawti.") else { throw Failure(message: "Sawti only removes devices it created") }
    guard let id = findDevice(uid: uid) else { return ["ok": true, "removed": false] }
    let status = AudioHardwareDestroyAggregateDevice(id)
    if status != noErr { throw Failure(message: "Could not remove device (status \(status))") }
    return ["ok": true, "removed": true]
}

func setRate(uid: String, rate: Double) throws -> [String: Any] {
    guard let id = findDevice(uid: uid) else { throw Failure(message: "Device not found") }
    var a = address(kAudioDevicePropertyNominalSampleRate)
    var value = Float64(rate)
    let status = AudioObjectSetPropertyData(id, &a, 0, nil, UInt32(MemoryLayout<Float64>.size), &value)
    if status != noErr { throw Failure(message: "Could not set sample rate (status \(status))") }
    _ = CFRunLoopRunInMode(CFRunLoopMode.defaultMode, 0.3, false)
    return ["ok": true, "rate": sampleRate(id)]
}

func setDefault(role: String, uid: String) throws -> [String: Any] {
    guard let id = findDevice(uid: uid) else { throw Failure(message: "Device not found") }
    let selector: AudioObjectPropertySelector
    switch role {
    case "input": selector = kAudioHardwarePropertyDefaultInputDevice
    case "output": selector = kAudioHardwarePropertyDefaultOutputDevice
    case "system": selector = kAudioHardwarePropertyDefaultSystemOutputDevice
    default: throw Failure(message: "role must be input, output or system")
    }
    var a = address(selector)
    var value = id
    let status = AudioObjectSetPropertyData(systemObject, &a, 0, nil, UInt32(MemoryLayout<AudioObjectID>.size), &value)
    if status != noErr { throw Failure(message: "Could not set default device (status \(status))") }
    return ["ok": true]
}

func option(_ name: String, _ args: [String]) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

func options(_ name: String, _ args: [String]) -> [String] {
    var out: [String] = []
    var i = 0
    while i < args.count {
        if args[i] == name, i + 1 < args.count { out.append(args[i + 1]); i += 2 } else { i += 1 }
    }
    return out
}

func emit(_ object: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: object, options: []),
       let text = String(data: data, encoding: .utf8) {
        print(text)
    } else {
        print("{\"ok\":false,\"error\":\"JSON encoding failed\"}")
    }
}

// Let the HAL use its own notification thread (recommended for command-line tools).
var runLoopAddress = address(kAudioHardwarePropertyRunLoop)
var noRunLoop: CFRunLoop? = nil
_ = AudioObjectSetPropertyData(systemObject, &runLoopAddress, 0, nil,
                               UInt32(MemoryLayout<CFRunLoop?>.size), &noRunLoop)

let args = Array(CommandLine.arguments.dropFirst())
do {
    switch args.first ?? "" {
    case "list":
        emit(listDevices())
    case "create":
        guard let name = option("--name", args), let uid = option("--uid", args),
              let main = option("--main", args) else { throw Failure(message: "create needs --name --uid --main") }
        let subs = options("--sub", args)
        guard !subs.isEmpty else { throw Failure(message: "create needs at least one --sub") }
        emit(try createAggregate(name: name, uid: uid, main: main, subs: subs, stacked: args.contains("--stacked")))
    case "destroy":
        guard let uid = option("--uid", args) else { throw Failure(message: "destroy needs --uid") }
        emit(try destroy(uid: uid))
    case "set-rate":
        guard let uid = option("--uid", args), let r = option("--rate", args), let rate = Double(r) else {
            throw Failure(message: "set-rate needs --uid --rate")
        }
        emit(try setRate(uid: uid, rate: rate))
    case "set-default":
        guard let uid = option("--uid", args), let role = option("--role", args) else {
            throw Failure(message: "set-default needs --role --uid")
        }
        emit(try setDefault(role: role, uid: uid))
    default:
        throw Failure(message: "unknown command")
    }
} catch let f as Failure {
    emit(["ok": false, "error": f.message])
    exit(1)
} catch {
    emit(["ok": false, "error": "\(error)"])
    exit(1)
}
