//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                        T r i b e M e n u                                       //
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
package com.notelite.omr.classifier.ui;

import com.notelite.omr.classifier.Sample;
import com.notelite.omr.classifier.SampleRepository;
import com.notelite.omr.classifier.SampleSheet;
import com.notelite.omr.classifier.Tribe;
import com.notelite.omr.glyph.Glyph;
import com.notelite.omr.glyph.Shape;
import com.notelite.omr.glyph.ShapeSet;
import com.notelite.omr.sheet.Sheet;
import com.notelite.omr.ui.OmrGui;
import com.notelite.omr.ui.util.SeparableMenu;

import org.jdesktop.application.Action;
import org.jdesktop.application.ApplicationActionMap;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.awt.event.ActionEvent;

import javax.swing.JMenu;
import javax.swing.JMenuItem;

/**
 * Class <code>TribeMenu</code>
 *
 * @author NoteLite Contributors
 */
public class TribeMenu
        extends SeparableMenu
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(SampleMenu.class);

    //~ Instance fields ----------------------------------------------------------------------------

    /** Selected glyph. */
    private final Glyph glyph;

    /** Containing sheet. */
    private final Sheet sheet;

    /** Related sample sheet, if any. */
    private SampleSheet sampleSheet;

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>TribeMenu</code> object.
     *
     * @param glyph the selected glyph
     * @param sheet the containing sheet
     */
    public TribeMenu (Glyph glyph,
                      Sheet sheet)
    {
        this.glyph = glyph;
        this.sheet = sheet;
        //
        //        final SampleRepository repository = SampleRepository.getGlobalInstance(true);
        //        sampleSheet = repository.pokeSampleSheet(sheet);
        //
        populateMenu();
    }

    //~ Methods ------------------------------------------------------------------------------------

    //---------//
    // addGood //
    //---------//
    /**
     * Add a good sample
     *
     * @param e triggering event
     */
    @Action
    public void addGood (ActionEvent e)
    {
        if (sampleSheet == null) {
            final SampleRepository repository = SampleRepository.getGlobalInstance();
            sampleSheet = repository.findSampleSheet(sheet);
        }

        final Tribe currentTribe = sampleSheet.getCurrentTribe(); // Cannot be null
        final Shape shape = currentTribe.getHead().getShape();
        final Glyph g = sheet.getGlyphIndex().registerOriginal(glyph);
        final Sample good = new Sample(g, sheet.getInterline(), shape, null);
        currentTribe.addGood(good);
        sampleSheet.setModified(true);
        logger.info("Added good {} to {}", good, currentTribe);
    }

    //----------//
    // addOther //
    //----------//
    /**
     * Add a plain sample
     *
     * @param e triggering event
     */
    @Action
    public void addOther (ActionEvent e)
    {
        if (sampleSheet == null) {
            final SampleRepository repository = SampleRepository.getGlobalInstance();
            sampleSheet = repository.findSampleSheet(sheet);
        }

        final Tribe currentTribe = sampleSheet.getCurrentTribe(); // Cannot be null
        final Shape shape = currentTribe.getHead().getShape();
        final Glyph g = sheet.getGlyphIndex().registerOriginal(glyph);
        final Sample other = new Sample(g, sheet.getInterline(), shape, null);
        currentTribe.addOther(other);
        sampleSheet.setModified(true);
        logger.info("Added other {} to {}", other, currentTribe);
    }

    //----------//
    // getGlyph //
    //----------//
    /**
     * @return the glyph
     */
    public Glyph getGlyph ()
    {
        return glyph;
    }

    //--------------//
    // populateMenu //
    //--------------//
    /**
     * Build the tribe menu, based on selected glyph.
     */
    private void populateMenu ()
    {
        setText(Integer.toString(glyph.getId()));

        ApplicationActionMap actionMap = OmrGui.getApplication().getContext().getActionMap(this);

        // Best: Start a new tribe with the glyph? Using manual shape selection
        add(new SelectMenu());

        Tribe currentTribe = (sampleSheet != null) ? sampleSheet.getCurrentTribe() : null;

        if (currentTribe != null) {
            // Good: Add compatible glyph to current tribe
            add(new JMenuItem(actionMap.get("addGood")));

            // Other: Add sub-optimal glyph to current tribe
            add(new JMenuItem(actionMap.get("addOther")));
        }
    }

    //------------//
    // selectBest //
    //------------//
    private void selectBest (Shape shape)
    {
        if (sampleSheet == null) {
            final SampleRepository repository = SampleRepository.getGlobalInstance();
            sampleSheet = repository.findSampleSheet(sheet);
        }

        final Glyph g = sheet.getGlyphIndex().registerOriginal(glyph);
        final Sample best = new Sample(g, sheet.getInterline(), shape, null);

        sampleSheet.getTribe(best);
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //------------//
    // SelectMenu //
    //------------//
    private class SelectMenu
            extends JMenu
    {
        SelectMenu ()
        {
            super("Set as Best");

            populate();
        }

        private void populate ()
        {
            ShapeSet.addAllShapes(sheet.getStub().getMusicFamily(), this, (ActionEvent e) ->
            {
                JMenuItem source = (JMenuItem) e.getSource();
                Shape shape = Shape.valueOf(source.getText());
                selectBest(shape);
            });
        }
    }
}
