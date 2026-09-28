/* SPDX-License-Identifier: GPL-2.0-only WITH Classpath-exception-2.0 */
package sun.awt;

import java.awt.GraphicsEnvironment;
import java.awt.Toolkit;

/** Platform entry point for an iOS runtime that renders only into images. */
public final class PlatformGraphicsInfo {
    // macOS peer classes remain in the module for binary compatibility, but
    // this runtime has no WindowServer session and never constructs those peers.
    public static boolean isInAquaSession() { return false; }
    private PlatformGraphicsInfo() {}
    public static GraphicsEnvironment createGE() { return new MobileGraphicsEnvironment(); }
    public static Toolkit createToolkit() { return new MobileToolkit(); }
    public static boolean getDefaultHeadlessProperty() { return true; }
    public static String getDefaultHeadlessMessage() {
        return "The embedded iOS OMR runtime supports offscreen graphics only.";
    }
}
