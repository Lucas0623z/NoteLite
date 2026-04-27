//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                        L i n k s S t e p                                       //
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
package com.notelite.omr.sheet.symbol;

import com.notelite.omr.constant.Constant;
import com.notelite.omr.constant.ConstantSet;
import com.notelite.omr.sheet.Sheet;
import com.notelite.omr.sheet.SystemInfo;
import com.notelite.omr.sheet.rhythm.MeasureFiller;
import com.notelite.omr.sig.BeamHeadCleaner;
import com.notelite.omr.sig.SigReducer;
import com.notelite.omr.sig.inter.HeadChordInter;
import com.notelite.omr.sig.inter.Inter;
import com.notelite.omr.sig.inter.LyricItemInter;
import com.notelite.omr.sig.inter.SentenceInter;
import com.notelite.omr.sig.inter.SlurInter;
import com.notelite.omr.sig.inter.TremoloInter;
import com.notelite.omr.sig.inter.WordInter;
import com.notelite.omr.sig.ui.AdditionTask;
import com.notelite.omr.sig.ui.InterTask;
import com.notelite.omr.sig.ui.SentenceRoleTask;
import com.notelite.omr.sig.ui.UITask;
import com.notelite.omr.sig.ui.UITask.OpKind;
import com.notelite.omr.sig.ui.UITaskList;
import com.notelite.omr.step.AbstractSystemStep;
import com.notelite.omr.step.StepException;
import com.notelite.omr.util.StopWatch;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Class <code>LinksStep</code> implements <b>LINKS</b> step, which assigns relations between
 * certain symbols and makes a final reduction.
 *
 * @author NoteLite Contributors
 */
public class LinksStep
        extends AbstractSystemStep<Void>
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(LinksStep.class);

    /** Classes that may impact texts. */
    private static final Set<Class<?>> forTexts;

    /** All impacting classes. */
    private static final Set<Class<?>> impactingClasses;

    static {
        forTexts = new HashSet<>();
        forTexts.add(WordInter.class);
        forTexts.add(SentenceInter.class);
    }

    static {
        impactingClasses = new HashSet<>();
        impactingClasses.addAll(forTexts);
    }

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>LinksStep</code> object.
     */
    public LinksStep ()
    {
    }

    //~ Methods ------------------------------------------------------------------------------------

    //----------//
    // doEpilog //
    //----------//
    @Override
    protected void doEpilog (Sheet sheet,
                             Void context)
        throws StepException
    {
        // Check for ties in same staff, now that head alterations and clef changes are available
        for (SystemInfo system : sheet.getSystems()) {
            List<Inter> systemHeadChords = system.getSig().inters(HeadChordInter.class);

            for (Inter inter : system.getSig().inters(SlurInter.class)) {
                SlurInter slur = (SlurInter) inter;
                slur.checkStaffTie(systemHeadChords);
            }
        }
    }

    //----------//
    // doSystem //
    //----------//
    @Override
    public void doSystem (SystemInfo system,
                          Void context)
        throws StepException
    {
        final StopWatch watch = new StopWatch("LinksStep doSystem #" + system.getId());

        // Fill each measure with all detected clef(s) and key if any
        // Because key change detection requires access to effective clef and key
        new MeasureFiller(system).process();

        watch.start("SymbolsLinker");
        new SymbolsLinker(system).process();

        // Reduction
        watch.start("reduceLinks");
        new SigReducer(system, true).reduceLinks();

        // Aggregate tremolos whenever needed
        TremoloInter.aggregate(system);

        // Complete each measure with clef(s) and key if any
        new MeasureFiller(system).process();

        // Purge deleted lyrics from containing part
        new InterCleaner(system).purgeContainers();

        // Remove all Beam-Head relations, now useless
        new BeamHeadCleaner(system).process();

        // Remove all free glyphs?
        if (constants.removeFreeGlyphs.isSet()) {
            system.clearFreeGlyphs();
        }

        if (constants.printWatch.isSet()) {
            watch.print();
        }
    }

    //--------//
    // impact //
    //--------//
    @Override
    public void impact (UITaskList seq,
                        OpKind opKind)
    {
        logger.debug("LINKS impact {} {}", opKind, seq);

        for (UITask task : seq.getTasks()) {
            if (task instanceof InterTask interTask) {
                final Inter inter = interTask.getInter();

                if (isImpactedBy(inter.getClass(), forTexts)) {
                    final SystemInfo system = inter.getSig().getSystem();

                    switch (inter) {
                        case LyricItemInter item -> {
                            if ((opKind != OpKind.UNDO) && task instanceof AdditionTask) {
                                final int profile = Math.max(
                                        item.getProfile(),
                                        system.getProfile());
                                item.mapToChord(profile);
                            }
                        }
                        case SentenceInter sentence -> {
                            if ((opKind != OpKind.UNDO) && task instanceof AdditionTask) {
                                sentence.link(system);
                            } else if (task instanceof SentenceRoleTask roleTask) {
                                sentence.unlink(
                                        (opKind == OpKind.UNDO) //
                                                ? roleTask.getNewRole()
                                                : roleTask.getOldRole());
                                sentence.link(system);
                            }
                        }
                        default -> {}
                    }
                }
            }
        }
    }

    //--------------//
    // isImpactedBy //
    //--------------//
    @Override
    public boolean isImpactedBy (Class<?> classe)
    {
        return isImpactedBy(classe, impactingClasses);
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Boolean printWatch = new Constant.Boolean(
                false,
                "Should we print out the stop watch?");

        private final Constant.Boolean removeFreeGlyphs = new Constant.Boolean(
                false,
                "Should we remove all free glyphs?");
    }
}
