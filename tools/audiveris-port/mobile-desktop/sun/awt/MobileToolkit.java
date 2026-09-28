/* SPDX-License-Identifier: GPL-2.0-only WITH Classpath-exception-2.0 */
package sun.awt;

import java.awt.*;
import java.awt.datatransfer.Clipboard;
import java.awt.font.TextAttribute;
import java.awt.im.InputMethodHighlight;
import java.awt.image.*;
import java.net.URL;
import java.util.Map;
import java.util.Properties;
import sun.awt.image.ByteArrayImageSource;
import sun.awt.image.FileImageSource;
import sun.awt.image.ToolkitImage;
import sun.awt.image.URLImageSource;
import sun.font.FontDesignMetrics;

/** Supplies image loading and metrics without constructing a Cocoa toolkit. */
public final class MobileToolkit extends Toolkit {
    private final EventQueue eventQueue = new EventQueue();

    @Override public Dimension getScreenSize() { throw new HeadlessException(); }
    @Override public int getScreenResolution() { throw new HeadlessException(); }
    @Override public ColorModel getColorModel() { return ColorModel.getRGBdefault(); }
    @Override public String[] getFontList() {
        return GraphicsEnvironment.getLocalGraphicsEnvironment().getAvailableFontFamilyNames();
    }
    @Override public FontMetrics getFontMetrics(Font font) { return FontDesignMetrics.getMetrics(font); }
    @Override public void sync() { /* Software BufferedImage rendering is synchronous. */ }
    @Override public Image getImage(String path) { return createImage(path); }
    @Override public Image getImage(URL url) { return createImage(url); }
    @Override public Image createImage(String path) { return createImage(new FileImageSource(path)); }
    @Override public Image createImage(URL url) { return createImage(new URLImageSource(url)); }
    @Override public Image createImage(ImageProducer producer) { return new ToolkitImage(producer); }
    @Override public Image createImage(byte[] bytes, int offset, int length) {
        return createImage(new ByteArrayImageSource(bytes, offset, length));
    }
    @Override public boolean prepareImage(Image image, int width, int height, ImageObserver observer) {
        if (width == 0 || height == 0 || !(image instanceof ToolkitImage toolkitImage)) return true;
        if (toolkitImage.hasError()) {
            if (observer != null) observer.imageUpdate(image, ImageObserver.ERROR | ImageObserver.ABORT,
                                                       -1, -1, -1, -1);
            return false;
        }
        return toolkitImage.getImageRep().prepare(observer);
    }
    @Override public int checkImage(Image image, int width, int height, ImageObserver observer) {
        if (!(image instanceof ToolkitImage toolkitImage)) return ImageObserver.ALLBITS;
        int representation = width == 0 || height == 0 ? ImageObserver.ALLBITS
                : toolkitImage.getImageRep().check(observer);
        return toolkitImage.check(observer) | representation;
    }
    @Override public PrintJob getPrintJob(Frame frame, String title, Properties properties) {
        throw new HeadlessException();
    }
    @Override public void beep() { throw new HeadlessException(); }
    @Override public Clipboard getSystemClipboard() { throw new HeadlessException(); }
    @Override protected EventQueue getSystemEventQueueImpl() { return eventQueue; }
    @Override public boolean isModalityTypeSupported(Dialog.ModalityType type) { return false; }
    @Override public boolean isModalExclusionTypeSupported(Dialog.ModalExclusionType type) { return false; }
    @Override public Map<TextAttribute, ?> mapInputMethodHighlight(InputMethodHighlight highlight) {
        throw new HeadlessException();
    }
}
