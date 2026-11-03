// 收息佬 · 菜单栏小程序
// 作用:启动内置的本地服务 → 打开浏览器;菜单栏显示「息」,可打开页面、复制手机访问地址、打开数据文件夹、退出。
// 只用 AppKit,编译后不到 200 KB。
import Cocoa

final class Delegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var server: Process?
    var port = 0
    var lanURL: String?
    var starting = true
    var failed = false

    let home = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/收息佬")
    var portFile: URL { home.appendingPathComponent("server.port") }
    var baseURL: URL? { port > 0 ? URL(string: "http://127.0.0.1:\(port)") : nil }

    func applicationDidFinishLaunching(_ n: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "息"
        statusItem.button?.toolTip = "收息佬"
        rebuildMenu()
        startServer()
    }

    // 再次双击图标(或从启动台打开):直接打开页面
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openBrowser()
        return true
    }

    func applicationWillTerminate(_ n: Notification) {
        if let p = server, p.isRunning {
            p.terminate()
            let end = Date().addingTimeInterval(1.5)
            while p.isRunning && Date() < end { Thread.sleep(forTimeInterval: 0.05) }
        }
    }

    // MARK: 服务
    func startServer() {
        starting = true; failed = false; lanURL = nil; port = 0
        try? FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        try? FileManager.default.removeItem(at: portFile)
        guard let res = Bundle.main.resourceURL else { return fail("找不到程序资源") }
        let exe = res.appendingPathComponent("server/shouxi-server")
        let p = Process()
        p.executableURL = exe
        var env = ProcessInfo.processInfo.environment
        env["SHOUXI_WATCH_PARENT"] = "1"
        p.environment = env
        let logURL = home.appendingPathComponent("server.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let fh = try? FileHandle(forWritingTo: logURL) { p.standardOutput = fh; p.standardError = fh }
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let s = self, !s.starting || s.port == 0 else { return }
                if NSApp.isRunning { s.fail("服务意外停止了") }
            }
        }
        do { try p.run() } catch { return fail("无法启动服务:\(error.localizedDescription)") }
        server = p
        waitForPort(tries: 80)
    }

    func waitForPort(tries: Int) {
        if let s = try? String(contentsOf: portFile, encoding: .utf8), let v = Int(s.trimmingCharacters(in: .whitespacesAndNewlines)) {
            port = v; starting = false
            openBrowser(); fetchLAN(); rebuildMenu()
            return
        }
        if tries <= 0 { return fail("服务没有在预期时间内启动") }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in self?.waitForPort(tries: tries - 1) }
    }

    func fail(_ msg: String) {
        failed = true; starting = false
        statusItem.button?.title = "息 ⚠"
        rebuildMenu()
        let a = NSAlert()
        a.messageText = "收息佬没能启动"
        a.informativeText = msg + "\n\n可以从菜单栏的「息」选择「重新启动服务」,或查看数据文件夹里的 server.log。"
        a.runModal()
    }

    func fetchLAN() {
        guard let u = baseURL?.appendingPathComponent("api/access") else { return }
        URLSession.shared.dataTask(with: u) { [weak self] data, _, _ in
            guard let d = data, let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
                  let urls = j["urls"] as? [String] else { return }
            DispatchQueue.main.async { self?.lanURL = urls.first; self?.rebuildMenu() }
        }.resume()
    }

    // MARK: 菜单
    func rebuildMenu() {
        let m = NSMenu()
        if failed {
            m.addItem(item("重新启动服务", #selector(restart)))
        } else if starting {
            let i = NSMenuItem(title: "正在启动…", action: nil, keyEquivalent: ""); i.isEnabled = false; m.addItem(i)
        } else {
            m.addItem(item("打开收息佬", #selector(openBrowser), "o"))
            m.addItem(.separator())
            let h = NSMenuItem(title: "手机访问(同一 WiFi)", action: nil, keyEquivalent: ""); h.isEnabled = false; m.addItem(h)
            if let u = lanURL {
                m.addItem(item("  \(u)  · 点击复制", #selector(copyLAN)))
            } else {
                let i = NSMenuItem(title: "  未检测到局域网地址", action: nil, keyEquivalent: ""); i.isEnabled = false; m.addItem(i)
            }
        }
        m.addItem(.separator())
        m.addItem(item("打开数据文件夹", #selector(openData)))
        m.addItem(.separator())
        m.addItem(item("退出收息佬", #selector(quit), "q"))
        statusItem.menu = m
    }

    func item(_ t: String, _ s: Selector, _ k: String = "") -> NSMenuItem {
        let i = NSMenuItem(title: t, action: s, keyEquivalent: k); i.target = self; return i
    }

    @objc func openBrowser() {
        if let u = baseURL { NSWorkspace.shared.open(u) }
    }
    @objc func copyLAN() {
        guard let u = lanURL else { return }
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(u, forType: .string)
    }
    @objc func openData() { NSWorkspace.shared.open(home) }
    @objc func restart() {
        if let p = server, p.isRunning { p.terminate() }
        statusItem.button?.title = "息"
        rebuildMenu(); startServer(); rebuildMenu()
    }
    @objc func quit() { NSApp.terminate(nil) }
}

let app = NSApplication.shared
let delegate = Delegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)   // 只在菜单栏,不占 Dock
app.run()
