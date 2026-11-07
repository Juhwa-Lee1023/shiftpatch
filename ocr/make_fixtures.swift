// Draw synthetic roster images for OCR tests. Same drawing approach as
// experiments/roster-ocr/roster_ocr.swift, plus layouts the review screen
// must flag (unknown name + collision) or refuse (unsupported headers).
// Usage: swift make_fixtures.swift <out-dir>
import Foundation
import AppKit

let base = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
let width: CGFloat = 1600, height: CGFloat = 800

func drawText(_ s: String, _ x: CGFloat, _ top: CGFloat, _ size: CGFloat, bold: Bool = false, color: NSColor = .black) {
    let font = NSFont(name: bold ? "AppleSDGothicNeo-Bold" : "AppleSDGothicNeo-Regular", size: size) ?? NSFont.systemFont(ofSize: size)
    (s as NSString).draw(at: NSPoint(x: x, y: height - top - size - 8), withAttributes: [.font: font, .foregroundColor: color])
}

func table(_ name: String, outputWidth: Int, title: String, subtitle: String, headers: [String], rows: [[String]]) throws {
    let scale = CGFloat(outputWidth) / width
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: outputWidth, pixelsHigh: Int(height * scale), bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let g = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = g
    g.cgContext.scaleBy(x: scale, y: scale)
    NSColor.white.setFill(); NSRect(x: 0, y: 0, width: width, height: height).fill()
    drawText(title, 60, 35, 48, bold: true)
    drawText(subtitle, 60, 105, 32)
    drawText("합성 데이터 · OCR 시험용", 60, 155, 25, color: .darkGray)
    let n = headers.count
    let colW = 1480 / CGFloat(n)
    let cols = (0...n).map { 60 + CGFloat($0) * colW }
    let tops: [CGFloat] = [230, 325] + (0..<rows.count).map { 440 + CGFloat($0) * 115 }
    NSColor(calibratedWhite: 0.93, alpha: 1).setFill()
    NSRect(x: 60, y: height - 325, width: 1480, height: 95).fill()
    NSColor.gray.setStroke()
    let bottom = tops.last!
    for x in cols { let q = NSBezierPath(); q.move(to: NSPoint(x: x, y: height - 230)); q.line(to: NSPoint(x: x, y: height - bottom)); q.stroke() }
    for y in tops { let q = NSBezierPath(); q.move(to: NSPoint(x: 60, y: height - y)); q.line(to: NSPoint(x: 1540, y: height - y)); q.stroke() }
    for i in 0..<n { drawText(headers[i], cols[i] + 20, 250, 32, bold: true) }
    for r in 0..<rows.count { for c in 0..<n { drawText(rows[r][c], cols[c] + 20, 350 + CGFloat(r) * 115, 35) } }
    NSGraphicsContext.restoreGraphicsState()
    try rep.representation(using: .png, properties: [:])!.write(to: base.appendingPathComponent(name + ".png"))
}

let h5 = ["이름", "날짜", "시작", "종료", "업무"]
try table("unknown_collision", outputWidth: 1600, title: "고객지원 근무표", subtitle: "2026년 11월 9일 (월)", headers: h5,
          rows: [["지안", "2026-11-09", "09:00", "13:00", "일반 문의"],
                 ["민지", "2026-11-09", "13:00", "17:00", "일반 문의"],
                 ["태오", "2026-11-09", "16:00", "18:00", "일반 문의"]])
try table("unsupported", outputWidth: 1600, title: "주간 메모", subtitle: "11월 둘째 주", headers: ["직원", "시간대"],
          rows: [["지안", "오전"], ["민수", "오후"], ["태오", "저녁"]])
print("ok")
