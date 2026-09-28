/* SPDX-License-Identifier: GPL-2.0-only WITH Classpath-exception-2.0 */
package sun.awt;

import java.awt.GraphicsDevice;
import java.awt.HeadlessException;
import sun.java2d.SunGraphicsEnvironment;

/** Uses OpenJDK's real software rasterizer for BufferedImage Graphics2D. */
public final class MobileGraphicsEnvironment extends SunGraphicsEnvironment {
    @Override protected int getNumScreens() { return 0; }
    @Override protected GraphicsDevice makeScreenDevice(int screen) { throw new HeadlessException(); }
    @Override public GraphicsDevice getDefaultScreenDevice() { throw new HeadlessException(); }
    @Override public boolean isDisplayLocal() { return true; }
}
