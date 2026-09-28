// Native OCR dependency test. It does not start Audiveris or an embedded JVM.
#include <leptonica/allheaders.h>
#include <tesseract/baseapi.h>
#include <tesseract/capi.h>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <string>

static void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main(int argc, char** argv) {
    require(argc == 2, "pass tessdata directory");
    std::printf("Tesseract %s; %s\n", tesseract::TessBaseAPI::Version(), getLeptonicaVersion());
    PIX* source = pixCreate(900, 160, 8);
    require(source != nullptr, "allocate source");
    require(pixSetAll(source) == 0, "white background");
    L_BMF* font = bmfCreate(nullptr, 20);
    require(font != nullptr, "built-in bitmap font");
    int overflow = 0;
    require(pixSetTextline(source, font, "HELLO WORLD 123", 0, 35, 100, nullptr, &overflow) == 0 && !overflow,
            "render synthetic OCR input");
    bmfDestroy(&font);
    pixSetResolution(source, 300, 300);

    l_uint8* buffer = nullptr;
    size_t count = 0;
    require(pixWriteMemPng(&buffer, &count, source, 0) == 0 && count > 0, "PNG encode");
    PIX* png = pixReadMemPng(buffer, count);
    lept_free(buffer);
    require(png != nullptr && pixGetWidth(png) == 900, "PNG decode");
    pixDestroy(&png);
    buffer = nullptr;
    count = 0;
    require(pixWriteMemJpeg(&buffer, &count, source, 95, 0) == 0 && count > 0, "JPEG encode");
    PIX* jpeg = pixReadMemJpeg(buffer, count, 0, 1, nullptr, 0);
    lept_free(buffer);
    require(jpeg != nullptr && pixGetHeight(jpeg) == 160, "JPEG decode");
    pixDestroy(&jpeg);

    PIX* binary = pixConvertTo1(source, 128);
    require(binary != nullptr, "TIFF binary source");
    buffer = nullptr;
    count = 0;
    require(pixWriteMemTiff(&buffer, &count, binary, IFF_TIFF_G4) == 0 && count > 0, "TIFF G4 encode");
    PIX* tiff = pixReadMemTiff(buffer, count, 0);
    lept_free(buffer);
    require(tiff != nullptr, "Audiveris pixReadMemTiff decode");
    int equal = 0;
    require(pixEqual(binary, tiff, &equal) == 0 && equal, "lossless TIFF round-trip");
    pixDestroy(&binary);
    pixDestroy(&source);

    // Audiveris TesseractOrder explicitly chooses OEM_TESSERACT_ONLY. Testing
    // only a tessdata_fast LSTM model would miss that required compatibility.
    for (auto mode : {tesseract::OEM_TESSERACT_ONLY, tesseract::OEM_LSTM_ONLY}) {
        tesseract::TessBaseAPI api;
        require(api.Init(argv[1], "eng", mode) == 0, "load pinned legacy + LSTM English model");
        api.SetPageSegMode(tesseract::PSM_SINGLE_LINE);
        api.SetImage(tiff);
        api.SetSourceResolution(300);
        require(api.Recognize(nullptr) == 0, "run real OCR");
        char* text = api.GetUTF8Text();
        require(text != nullptr, "OCR output");
        std::string normalized;
        for (const unsigned char* cursor = reinterpret_cast<unsigned char*>(text); *cursor; ++cursor) {
            if (!std::isspace(*cursor)) normalized.push_back(static_cast<char>(*cursor));
        }
        std::printf("OCR mode %d text: %s\n", static_cast<int>(mode), text);
        delete[] text;
        require(normalized == "HELLOWORLD123", "expected synthetic text recognized");
        api.End();
    }
    pixDestroy(&tiff);
    std::puts("PASS: PNG/JPEG/TIFF codecs and real legacy + LSTM Tesseract OCR; static JNI symbols linked; Java VM not executed.");
    return 0;
}
