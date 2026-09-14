// ClassSlides — capture lecture slides from the Microsoft Teams meeting window ONLY.
//
//   open -n ClassSlides.app --args <frames-dir> [seconds-between-frames] [max-minutes]
//
// SECURITY MODEL. This replaces full-screen ffmpeg capture, which needed the terminal to
// hold macOS Screen Recording permission (a grant any program run in that terminal inherits).
//   * No Screen Recording permission. Access comes from Apple's system window picker
//     (SCContentSharingPicker): you pick the window yourself, per session, in trusted
//     system UI. Nothing persists after the app quits.
//   * Teams only. Picker is locked to single-window mode; any window not owned by
//     Microsoft Teams is refused and the app quits. Only that window's pixels are
//     captured — overlapping windows (terminal, chats) never appear in a frame.
//   * App Sandbox, enforced by macOS: no network entitlement (cannot send anything), and
//     file access ONLY to ~/class-notes/.frames -- a staging folder. capture-slides.sh, not
//     this app, moves finished frames into the course's slides folder, so the app can never
//     touch scripts, notes or .env (see build.sh entitlements).
//   * Meeting windows only: the main Teams window and popped-out chats (titles ending in
//     "| Microsoft Teams") are refused too.
//   * Hard stop, quit when the Teams window closes, every START/STOP/REFUSED line in
//     ~/class-notes/screen-capture-audit.log.

import AppKit
import CoreImage
import Darwin
import ScreenCaptureKit

let teamsBundleIDs: Set<String> = ["com.microsoft.teams2", "com.microsoft.teams"]

func realHome() -> String { String(cString: getpwuid(getuid())!.pointee.pw_dir) }  // sandbox-safe

final class Capture: NSObject, NSApplicationDelegate, SCContentSharingPickerObserver,
                     SCStreamOutput, SCStreamDelegate {
  let outDir: URL, interval: Double, maxMinutes: Int
  let root = URL(fileURLWithPath: realHome() + "/class-notes/.frames")  // the sandbox's only writable path
  var stream: SCStream?
  var frameNo = 0
  var lastWrite = Date.distantPast
  var finished = false
  var signalSources: [DispatchSourceSignal] = []
  let ci = CIContext()
  let queue = DispatchQueue(label: "classslides.frames")

  init(outDir: URL, interval: Double, maxMinutes: Int) {
    self.outDir = outDir; self.interval = interval; self.maxMinutes = maxMinutes
  }

  func audit(_ msg: String) {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm:ss"
    let line = "\(f.string(from: Date()))  \(msg)\n"
    let url = root.appendingPathComponent("screen-capture-audit.log")
    if let h = try? FileHandle(forWritingTo: url) {
      h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close()
    }
  }

  func applicationDidFinishLaunching(_ note: Notification) {
    try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
    try? "\(getpid())".write(to: outDir.appendingPathComponent(".pid"), atomically: true, encoding: .utf8)

    // Stop cleanly on SIGINT/SIGTERM — capture-slides.sh stop sends SIGINT.
    for sig in [SIGINT, SIGTERM] {
      signal(sig, SIG_IGN)
      let s = DispatchSource.makeSignalSource(signal: sig, queue: .main)
      s.setEventHandler { [weak self] in self?.finish("stopped by signal \(sig)") }
      s.resume(); signalSources.append(s)
    }
    // Hard stop, and give up if no window is picked within 5 minutes.
    DispatchQueue.main.asyncAfter(deadline: .now() + .seconds(maxMinutes * 60)) { [weak self] in
      self?.finish("hard stop \(self?.maxMinutes ?? 0)min")
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 300) { [weak self] in
      if self?.stream == nil { self?.finish("no window picked within 5 min") }
    }

    var cfg = SCContentSharingPickerConfiguration()
    cfg.allowedPickerModes = [.singleWindow]
    cfg.allowsChangingSelectedContent = false
    let picker = SCContentSharingPicker.shared
    picker.defaultConfiguration = cfg
    picker.add(self)
    picker.isActive = true
    NSApp.activate(ignoringOtherApps: true)
    picker.present(using: .window)
    audit("PICKER dir=\(outDir.path) interval=\(Int(interval))s max=\(maxMinutes)min pid=\(getpid())")
  }

  // MARK: picker

  func contentSharingPicker(_ picker: SCContentSharingPicker, didUpdateWith filter: SCContentFilter,
                            for stream: SCStream?) {
    DispatchQueue.main.async { self.startStream(filter) }
  }

  func contentSharingPicker(_ picker: SCContentSharingPicker, didCancelFor stream: SCStream?) {
    DispatchQueue.main.async { self.finish("picker cancelled") }
  }

  func contentSharingPickerStartDidFailWithError(_ error: Error) {
    DispatchQueue.main.async { self.finish("picker failed: \(error.localizedDescription)") }
  }

  func startStream(_ filter: SCContentFilter) {
    guard stream == nil, !finished else { return }
    let wins = filter.includedWindows
    guard wins.count == 1, let owner = wins[0].owningApplication,
          teamsBundleIDs.contains(owner.bundleIdentifier) else {
      let who = wins.map { $0.owningApplication?.bundleIdentifier ?? "?" }.joined(separator: ",")
      finish("REFUSED non-Teams selection (\(who.isEmpty ? "not a single window" : who))")
      return
    }
    // Teams, but not a meeting: the main window ("Chat | …", "Teams and Channels | Microsoft
    // Teams", Calendar, Activity) and popped-out chats carry the "| Microsoft Teams" suffix and
    // would capture private conversations. The meeting window is titled with the meeting name
    // alone (observed 2026-09-14), so refuse the suffix and untitled windows.
    let title = wins[0].title ?? ""
    if title.isEmpty || title.hasSuffix("| Microsoft Teams") {
      finish("REFUSED Teams window that is not a meeting (title=\"\(title)\")")
      return
    }
    let conf = SCStreamConfiguration()
    let scale = CGFloat(filter.pointPixelScale)
    let w = min(filter.contentRect.width * scale, 1600)
    conf.width = Int(w)
    conf.height = Int(w * filter.contentRect.height / max(filter.contentRect.width, 1))
    conf.minimumFrameInterval = CMTime(value: 1, timescale: 1)
    conf.showsCursor = false
    conf.capturesAudio = false
    let s = SCStream(filter: filter, configuration: conf, delegate: self)
    do {
      try s.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
    } catch { finish("stream setup failed: \(error.localizedDescription)"); return }
    stream = s
    s.startCapture { [weak self] err in
      if let err { DispatchQueue.main.async { self?.finish("capture failed: \(err.localizedDescription)") } }
    }
    audit("START  dir=\(outDir.path) window=\"\(wins[0].title ?? "")\" app=\(owner.bundleIdentifier) interval=\(Int(interval))s max=\(maxMinutes)min pid=\(getpid())")
  }

  // MARK: frames

  func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
    guard type == .screen, sb.isValid, Date().timeIntervalSince(lastWrite) >= interval,
          let info = CMSampleBufferGetSampleAttachmentsArray(sb, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
          let raw = info.first?[.status] as? Int, SCFrameStatus(rawValue: raw) == .complete,
          let px = sb.imageBuffer else { return }
    let img = CIImage(cvPixelBuffer: px)
    guard let jpg = ci.jpegRepresentation(of: img, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
                                          options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.8])
    else { return }
    frameNo += 1
    lastWrite = Date()
    try? jpg.write(to: outDir.appendingPathComponent(String(format: "%05d.jpg", frameNo)), options: .atomic)
  }

  func stream(_ stream: SCStream, didStopWithError error: Error) {
    DispatchQueue.main.async { self.finish("stream ended (Teams window closed?): \(error.localizedDescription)") }
  }

  // MARK: teardown

  func finish(_ reason: String) {
    guard !finished else { return }
    finished = true
    let done = {
      SCContentSharingPicker.shared.isActive = false
      // .pid is left in place on purpose: capture-slides.sh stop needs it to find the frames
      // dir and dedup, even when the app quit on its own (Teams meeting window closed).
      self.audit("STOP   dir=\(self.outDir.path) frames=\(self.frameNo) reason=\(reason)")
      exit(0)
    }
    if let s = stream {
      s.stopCapture { _ in DispatchQueue.main.async { done() } }
      DispatchQueue.main.asyncAfter(deadline: .now() + 5) { done() }  // never hang on stop
    } else { done() }
  }
}

// MARK: main — validate arguments before touching anything

let args = CommandLine.arguments
guard args.count >= 2 else {
  FileHandle.standardError.write("usage: ClassSlides <frames-dir> [interval-s] [max-min]\n".data(using: .utf8)!)
  exit(2)
}
let rootPath = URL(fileURLWithPath: realHome() + "/class-notes/.frames").resolvingSymlinksInPath().path + "/"
let out = URL(fileURLWithPath: (args[1] as NSString).expandingTildeInPath).standardizedFileURL
guard (out.resolvingSymlinksInPath().path + "/").hasPrefix(rootPath), !out.path.contains("/../") else {
  FileHandle.standardError.write("error: refusing to capture outside ~/class-notes/.frames (\(out.path))\n".data(using: .utf8)!)
  exit(1)
}
let interval = max(Double(args.count > 2 ? args[2] : "10") ?? 10, 2)
let maxMin = min(max(Int(args.count > 3 ? args[3] : "210") ?? 210, 1), 210)

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = Capture(outDir: out, interval: interval, maxMinutes: maxMin)
app.delegate = delegate
app.run()
