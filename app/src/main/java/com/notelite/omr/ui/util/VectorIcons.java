//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                     V e c t o r I c o n s                                      //
//                                                                                                //
//------------------------------------------------------------------------------------------------//
// <editor-fold defaultstate="collapsed" desc="hdr">
//
//  Copyright © NoteLite 2026. All rights reserved.
//
//  This program is free software: you can redistribute it and/or modify it under the terms of the
//  GNU Affero General Public License as published by the Free Software Foundation, either version
//  3 of the License, or (at your option) any later version.
//
//  This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
//  without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
//  See the GNU Affero General Public License for more details.
//
//  You should have received a copy of the GNU Affero General Public License along with this
//  program.  If not, see <http://www.gnu.org/licenses/>.
//------------------------------------------------------------------------------------------------//
// </editor-fold>
package com.notelite.omr.ui.util;

import com.formdev.flatlaf.extras.FlatSVGIcon;

import org.jdesktop.application.ResourceConverter;
import org.jdesktop.application.ResourceMap;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Field;
import java.net.URL;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.swing.Icon;
import javax.swing.ImageIcon;

/**
 * Class <code>VectorIcons</code> substitutes scalable SVG icons for the legacy Crystal
 * PNG icons referenced from the BSAF .properties files.
 * <p>
 * A crystal reference like <code>/crystal/22x22/actions/undo.png</code> is redirected to the
 * classpath resource <code>svg/undo.svg</code>, rendered via {@link FlatSVGIcon} at the size
 * implied by the crystal folder (22 or 32). When no SVG replacement exists, the original PNG
 * is loaded as before, so the substitution is always safe.
 * <p>
 * {@link #install()} must be called once, before the Swing application is launched.
 *
 * @author NoteLite Contributors
 */
public abstract class VectorIcons
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(VectorIcons.class);

    /** Matches e.g. "/crystal/22x22/actions/undo.png", capturing size and base name. */
    private static final Pattern CRYSTAL_PATTERN = Pattern.compile(
            "^/?crystal/(\\d+)x\\d+/.+/([^/]+)\\.png$");

    /** Where the SVG replacements live on the classpath. */
    private static final String SVG_ROOT = "svg/";

    private static boolean installed = false;

    //~ Constructors -------------------------------------------------------------------------------

    private VectorIcons ()
    {
    }

    //~ Static Methods -----------------------------------------------------------------------------

    //---------//
    // install //
    //---------//
    /**
     * Register the SVG-substituting resource converter ahead of the BSAF default
     * icon converter.
     * <p>
     * BSAF <code>ResourceConverter.forType()</code> returns the <b>first</b> registered converter
     * that supports the requested type, and the default <code>IconStringConverter</code> is
     * registered by the static initializer of {@link ResourceMap}. To win regardless of class
     * loading order, the converter is inserted at the head of the (private) converter list.
     */
    public static synchronized void install ()
    {
        if (installed) {
            return;
        }

        installed = true;

        final SvgIconConverter converter = new SvgIconConverter();

        try {
            final Field field = ResourceConverter.class.getDeclaredField("resourceConverters");
            field.setAccessible(true);

            @SuppressWarnings("unchecked")
            final List<ResourceConverter> converters = (List<ResourceConverter>) field.get(null);
            converters.add(0, converter);
            logger.debug("VectorIcons converter installed (head of converter list)");
        } catch (ReflectiveOperationException | SecurityException ex) {
            // Fallback: plain registration, effective as long as ResourceMap is not yet loaded
            logger.warn("VectorIcons could not prepend converter, using plain registration", ex);
            ResourceConverter.register(converter);
        }
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //------------------//
    // SvgIconConverter //
    //------------------//
    private static class SvgIconConverter
            extends ResourceConverter
    {
        SvgIconConverter ()
        {
            super(Icon.class);
        }

        @Override
        public Object parseString (String s,
                                   ResourceMap resourceMap)
            throws ResourceConverterException
        {
            final Matcher matcher = CRYSTAL_PATTERN.matcher(s);

            if (matcher.matches()) {
                final int size = Integer.parseInt(matcher.group(1));
                final String name = SVG_ROOT + matcher.group(2) + ".svg";
                final ClassLoader loader = resourceMap.getClassLoader();

                if (loader.getResource(name) != null) {
                    return new FlatSVGIcon(name, size, size, loader);
                }

                logger.debug("No SVG replacement for {}", s);
            }

            // Fallback: legacy PNG loading, replicated from BSAF IconStringConverter
            return loadImageIcon(s, resourceMap);
        }

        @Override
        public boolean supportsType (Class testType)
        {
            return testType.equals(Icon.class) || testType.equals(ImageIcon.class);
        }

        private ImageIcon loadImageIcon (String s,
                                         ResourceMap resourceMap)
            throws ResourceConverterException
        {
            final String rPath;

            if (s.startsWith("/")) {
                rPath = (s.length() > 1) ? s.substring(1) : null;
            } else {
                rPath = resourceMap.getResourcesDir() + s;
            }

            if (rPath == null) {
                throw new ResourceConverterException("invalid image/icon path", s);
            }

            final URL url = resourceMap.getClassLoader().getResource(rPath);

            if (url == null) {
                throw new ResourceConverterException("couldn't find Icon resource", s);
            }

            return new ImageIcon(url);
        }
    }
}
