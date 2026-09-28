/* SPDX-License-Identifier: GPL-2.0-only WITH Classpath-exception-2.0 */
package sun.font;

/** Selects the bundled-file font manager instead of macOS CFontManager. */
final class PlatformFontInfo {
    static FontManager createFontManager() { return new MobileFontManager(); }
}
