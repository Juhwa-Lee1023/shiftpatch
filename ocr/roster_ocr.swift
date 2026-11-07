// Recognize text in one local image with Apple Vision and print JSON.
// Adapted from experiments/roster-ocr/roster_ocr.swift (same request
// settings), reduced to a single-file reader with pixel bounds.
// Usage: roster_ocr <image-path> <min-px> <max-px>
import Foundation
import Vision
import ImageIO

func fail(_ code: String) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: ["error": code])
    FileHandle.standardOutput.write(data)
    exit(2)
}

let args = CommandLine.arguments
guard args.count == 4, let minPx = Int(args[2]), let maxPx = Int(args[3]) else { fail("USAGE") }
let url = URL(fileURLWithPath: args[1])
guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
      let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any],
      let w = props[kCGImagePropertyPixelWidth] as? Int,
      let h = props[kCGImagePropertyPixelHeight] as? Int else { fail("UNREADABLE_IMAGE") }
if w < minPx || h < minPx / 2 { fail("IMAGE_TOO_SMALL") }
if w > maxPx || h > maxPx { fail("IMAGE_TOO_LARGE") }

let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false
let supported = (try? req.supportedRecognitionLanguages()) ?? []
req.recognitionLanguages = ["ko-KR", "en-US"].filter { supported.contains($0) }
let started = Date()
do {
    try VNImageRequestHandler(url: url, options: [:]).perform([req])
} catch {
    fail("VISION_FAILED")
}
let observations = (req.results ?? []).map { ob -> [String: Any] in
    let b = ob.boundingBox
    let top = ob.topCandidates(1).first
    return ["text": top?.string ?? "", "confidence": top?.confidence ?? 0,
            "bbox": ["x": b.origin.x, "y": b.origin.y, "width": b.width, "height": b.height]]
}
let out: [String: Any] = ["width": w, "height": h, "engine": "Apple Vision VNRecognizeTextRequest",
                          "revision": req.revision, "languages": req.recognitionLanguages,
                          "seconds": Date().timeIntervalSince(started), "observations": observations]
FileHandle.standardOutput.write(try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]))
