/* SPDX-License-Identifier: GPL-2.0-only WITH Classpath-exception-2.0 */
package sun.font;

import java.io.File;
import sun.awt.FontConfiguration;

/** Uses OpenJDK's TrueType/OpenType reader, HarfBuzz and FreeType on bundled fonts. */
public final class MobileFontManager extends SunFontManager {
    static String bundledFontDirectory() {
        return System.getProperty("notelite.omr.fontDirectory", getJDKFontDir());
    }

    static String defaultFontFile() {
        String path = System.getProperty("notelite.omr.defaultFontFile",
                new File(bundledFontDirectory(), "FinaleJazzText.otf").getPath());
        if (!new File(path).isFile()) {
            throw new IllegalStateException("Bundled OMR text font is missing: " + path);
        }
        return path;
    }

    static String defaultFontFace() {
        return System.getProperty("notelite.omr.defaultFontFace", "FinaleJazzText");
    }

    @Override protected String getFontPath(boolean noType1Fonts) { return bundledFontDirectory(); }
    @Override protected String[] getDefaultPlatformFont() {
        return new String[] { defaultFontFace(), defaultFontFile() };
    }
    @Override protected FontConfiguration createFontConfiguration() {
        return new MobileFontConfiguration(this);
    }
    @Override public FontConfiguration createFontConfiguration(boolean preferLocaleFonts,
                                                               boolean preferPropFonts) {
        return new MobileFontConfiguration(this);
    }
}
