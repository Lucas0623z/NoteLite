/* SPDX-License-Identifier: GPL-2.0-only WITH Classpath-exception-2.0 */
package sun.font;

import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.HashSet;
import sun.awt.FontConfiguration;

/** Explicit logical font mapping; music fonts are loaded from their original files. */
final class MobileFontConfiguration extends FontConfiguration {
    private final String file;
    private final String face;

    MobileFontConfiguration(SunFontManager manager) {
        super(manager);
        file = MobileFontManager.defaultFontFile();
        face = MobileFontManager.defaultFontFace();
        setFontConfiguration();
    }

    @Override public synchronized boolean init() { return true; }
    @Override public String getExtraFontPath() { return MobileFontManager.bundledFontDirectory(); }
    @Override public int getNumberCoreFonts() { return 1; }
    @Override public String[] getPlatformFontNames() { return new String[] { face }; }
    @Override public String getFileNameFromPlatformName(String name) { return file; }
    @Override public String getFallbackFamilyName(String name, String fallback) { return fallback; }
    @Override public boolean fontFilesArePresent() { return true; }
    @Override public boolean needToSearchForFile(String name) { return false; }
    @Override public String getVersion() { return "1"; }
    @Override public HashSet<String> getAWTFontPathSet() { return new HashSet<>(); }
    @Override protected void initReorderMap() { reorderMap = new HashMap<>(); }
    @Override protected String getEncoding(String name, String subset) { return "UTF-8"; }
    @Override protected Charset getDefaultFontCharset(String name) { return StandardCharsets.UTF_8; }
    @Override protected String getFaceNameFromComponentFontName(String name) { return face; }
    @Override protected String getFileNameFromComponentFontName(String name) { return file; }

    @Override public CompositeFontDescriptor[] get2DCompositeFontInfo() {
        String[] families = { "serif", "sansserif", "monospaced", "dialog", "dialoginput" };
        String[] styles = { "plain", "bold", "italic", "bolditalic" };
        CompositeFontDescriptor[] descriptors = new CompositeFontDescriptor[families.length * styles.length];
        int index = 0;
        for (String family : families) {
            for (String style : styles) {
                descriptors[index++] = new CompositeFontDescriptor(family + "." + style, 1,
                        new String[] { face }, new String[] { file }, new int[0], new int[] { 0 });
            }
        }
        return descriptors;
    }
}
