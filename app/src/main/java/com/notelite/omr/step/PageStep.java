//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                         P a g e S t e p                                        //
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
package com.notelite.omr.step;

import com.notelite.omr.score.MeasureFixer;
import com.notelite.omr.score.Page;
import com.notelite.omr.score.Score;
import com.notelite.omr.score.ScoreReduction;
import com.notelite.omr.sheet.Sheet;
import com.notelite.omr.sheet.SheetReduction;
import com.notelite.omr.sheet.SheetStub;
import com.notelite.omr.sheet.SystemInfo;
import com.notelite.omr.sheet.rhythm.MeasureStack;
import com.notelite.omr.sheet.rhythm.Voices;
import com.notelite.omr.sig.SIGraph;
import com.notelite.omr.sig.inter.AbstractTimeInter;
import com.notelite.omr.sig.inter.AugmentationDotInter;
import com.notelite.omr.sig.inter.BarlineInter;
import com.notelite.omr.sig.inter.BeamHookInter;
import com.notelite.omr.sig.inter.BeamInter;
import com.notelite.omr.sig.inter.BraceInter;
import com.notelite.omr.sig.inter.FlagInter;
import com.notelite.omr.sig.inter.HeadChordInter;
import com.notelite.omr.sig.inter.HeadInter;
import com.notelite.omr.sig.inter.Inter;
import com.notelite.omr.sig.inter.LyricItemInter;
import com.notelite.omr.sig.inter.LyricLineInter;
import com.notelite.omr.sig.inter.MeasureRepeatInter;
import com.notelite.omr.sig.inter.RestChordInter;
import com.notelite.omr.sig.inter.RestInter;
import com.notelite.omr.sig.inter.SentenceInter;
import com.notelite.omr.sig.inter.SlurInter;
import com.notelite.omr.sig.inter.StaffBarlineInter;
import com.notelite.omr.sig.inter.StemInter;
import com.notelite.omr.sig.inter.TimeNumberInter;
import com.notelite.omr.sig.inter.TupletInter;
import com.notelite.omr.sig.inter.WordInter;
import com.notelite.omr.sig.relation.AugmentationRelation;
import com.notelite.omr.sig.relation.DoubleDotRelation;
import com.notelite.omr.sig.relation.NextInVoiceRelation;
import com.notelite.omr.sig.relation.Relation;
import com.notelite.omr.sig.relation.SameTimeRelation;
import com.notelite.omr.sig.relation.SeparateTimeRelation;
import com.notelite.omr.sig.relation.SeparateVoiceRelation;
import com.notelite.omr.sig.relation.SlurHeadRelation;
import com.notelite.omr.sig.ui.ConnectionTask;
import com.notelite.omr.sig.ui.InterTask;
import com.notelite.omr.sig.ui.PageTask;
import com.notelite.omr.sig.ui.RelationTask;
import com.notelite.omr.sig.ui.StackTask;
import com.notelite.omr.sig.ui.SystemMergeTask;
import com.notelite.omr.sig.ui.UITask;
import com.notelite.omr.sig.ui.UITask.OpKind;
import com.notelite.omr.sig.ui.UITaskList;
import com.notelite.omr.text.TextRole;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import java.util.Set;

/**
 * Class <code>PageStep</code> handles connections between systems in a page.
 * <ul>
 * <li>Duplicated inters between systems are resolved.</li>
 * <li>Physical system Part instances are abstracted into LogicalPart instances.</li>
 * <li>Slurs are connected across systems.</li>
 * <li>Tied voices.</li>
 * <li>Refined lyric syllables.</li>
 * </ul>
 *
 * @author NoteLite Contributors
 */
public class PageStep
        extends AbstractStep
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(PageStep.class);

    private static final Impact WHOLE_IMPACT = new Impact(true, true, true, true, true);

    /** Classes that may impact voices. */
    private static final Set<Class<?>> forVoices;

    /** Classes that may impact lyrics. */
    private static final Set<Class<?>> forLyrics;

    /** Classes that may impact slurs. */
    private static final Set<Class<?>> forSlurs;

    /** Classes that may impact parts. */
    private static final Set<Class<?>> forParts;

    /** Classes that may impact measures. */
    private static final Set<Class<?>> forMeasures;

    /** All impacting classes. */
    private static final Set<Class<?>> impactingClasses;

    static {
        forVoices = new HashSet<>();
        // Inters
        forVoices.add(AbstractTimeInter.class);
        forVoices.add(AugmentationDotInter.class);
        forVoices.add(BarlineInter.class);
        forVoices.add(BeamHookInter.class);
        forVoices.add(BeamInter.class);
        forVoices.add(FlagInter.class);
        forVoices.add(HeadChordInter.class);
        forVoices.add(HeadInter.class);
        forVoices.add(MeasureStack.class);
        forVoices.add(RestChordInter.class);
        forVoices.add(RestInter.class);
        forVoices.add(SlurInter.class);
        forVoices.add(StemInter.class);
        forVoices.add(StaffBarlineInter.class);
        forVoices.add(TimeNumberInter.class);
        forVoices.add(TupletInter.class);
        // Relations
        forVoices.add(AugmentationRelation.class);
        forVoices.add(NextInVoiceRelation.class);
        forVoices.add(SameTimeRelation.class);
        forVoices.add(SeparateTimeRelation.class);
        forVoices.add(SeparateVoiceRelation.class);
        forVoices.add(DoubleDotRelation.class);
        // Tasks
        forVoices.add(SystemMergeTask.class);
    }

    static {
        forLyrics = new HashSet<>();
        forLyrics.add(LyricItemInter.class);
        forLyrics.add(LyricLineInter.class);
    }

    static {
        forSlurs = new HashSet<>();
        // Inters
        forSlurs.add(SlurInter.class);
        // Relations
        forSlurs.add(SlurHeadRelation.class);
    }

    static {
        forParts = new HashSet<>();
        forParts.add(BraceInter.class);
        forParts.add(SentenceInter.class);
        forParts.add(WordInter.class);
    }

    static {
        forMeasures = new HashSet<>();
        // Inters
        forMeasures.add(BarlineInter.class);
        forMeasures.add(MeasureRepeatInter.class);
        forMeasures.add(StaffBarlineInter.class);
        // Tasks
        forMeasures.add(SystemMergeTask.class);
    }

    static {
        impactingClasses = new HashSet<>();
        impactingClasses.addAll(forVoices);
        impactingClasses.addAll(forLyrics);
        impactingClasses.addAll(forSlurs);
        impactingClasses.addAll(forParts);
        impactingClasses.addAll(forMeasures);
    }

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>PageStep</code> object.
     */
    public PageStep ()
    {
    }

    //~ Methods ------------------------------------------------------------------------------------

    //------//
    // doit //
    //------//
    @Override
    public void doit (Sheet sheet)
        throws StepException
    {
        // Clean up gutter between systems one under the other
        new SheetReduction(sheet).process();

        for (Page page : sheet.getPages()) {
            processPage(page);
        }
    }

    //---------------//
    // doProcessPage //
    //---------------//
    private void doProcessPage (Page page,
                                Impact impact)
    {
        if (impact.onParts) {
            // Collate parts into logicals
            final Score score = page.getScore();
            final List<SheetStub> theStubs = score.getBook().getValidSelectedStubs();
            new ScoreReduction(score).reduce(theStubs);
        }

        if (impact.onMeasures) {
            // Merge / renumber measure stacks within the page
            new MeasureFixer().process(page);
        }

        if (impact.onSlurs) {
            // Inter-system slurs connections
            page.connectOrphanSlurs();
            page.checkPageCrossTies();
        }

        if (impact.onLyrics) {
            // Lyrics
            refineLyrics(page);
        }

        if (impact.onVoices) {
            // Refine voices IDs (and thus colors) across all systems of the page
            Voices.refinePage(page);
        }
    }

    //--------//
    // impact //
    //--------//
    @Override
    public void impact (UITaskList seq,
                        OpKind opKind)
    {
        logger.debug("PAGE impact {} {}", opKind, seq);

        // First, determine what will be impacted
        final SIGraph sig = seq.getSig();
        final Map<Page, Impact> map = new LinkedHashMap<>();

        for (UITask task : seq.getTasks()) {
            switch (task) {
                case InterTask interTask -> {
                    final Inter inter = interTask.getInter();
                    final Page page = inter.getSig().getSystem().getPage();
                    final Impact impact = getImpact(map, page);
                    final Class classe = inter.getClass();

                    if (isImpactedBy(classe, forParts)) {
                        switch (inter) {
                            case SentenceInter sentenceInter -> {
                                if (sentenceInter.getRole() == TextRole.PartName) {
                                    impact.onParts = true;
                                }
                            }

                            case WordInter wordInter -> {
                                final SentenceInter sentence = (SentenceInter) wordInter
                                        .getEnsemble();
                                if (sentence != null && sentence.getRole() == TextRole.PartName) {
                                    impact.onParts = true;
                                }
                            }

                            default -> impact.onParts = true;
                        }
                    }

                    if (isImpactedBy(classe, forSlurs)) {
                        impact.onSlurs = true;
                    }

                    if (isImpactedBy(classe, forLyrics)) {
                        impact.onLyrics = true;
                    }

                    if (isImpactedBy(classe, forVoices)) {
                        impact.onVoices = true;
                        impact.onMeasures = true; // Since measure specials can depend on voices
                    }

                    if (isImpactedBy(classe, forMeasures)) {
                        impact.onMeasures = true;
                    }
                }

                case StackTask stackTask -> {
                    final MeasureStack stack = stackTask.getStack();
                    final Class classe = stack.getClass();
                    final Page page = stack.getSystem().getPage();
                    final Impact impact = getImpact(map, page);

                    if (isImpactedBy(classe, forVoices)) {
                        impact.onVoices = true;
                    }
                }

                case PageTask pageTask -> {
                    final Page page = pageTask.getPage();
                    final Impact impact = getImpact(map, page);
                    impact.onParts = true; // Safer
                    impact.onMeasures = true;
                    impact.onSlurs = true;
                    impact.onVoices = true;
                }

                case SystemMergeTask systemMergeTask -> {
                    final Page page = systemMergeTask.getSystem().getPage();
                    final Impact impact = getImpact(map, page);
                    impact.onParts = true;
                    impact.onMeasures = true;
                    impact.onVoices = true;
                }

                case RelationTask relationTask -> {
                    final Page page = sig.getSystem().getPage();
                    final Impact impact = getImpact(map, page);
                    final Relation relation = relationTask.getRelation();
                    final Class classe = relation.getClass();

                    if (isImpactedBy(classe, forVoices)) {
                        impact.onVoices = true;
                    }

                    if (isImpactedBy(classe, forSlurs)) {
                        impact.onSlurs = true;
                    }
                }

                case ConnectionTask connectionTask -> {
                    final Page page = connectionTask.getPage();
                    final Impact impact = getImpact(map, page);
                    impact.onVoices = true;
                    impact.onSlurs = true;
                }

                default -> {}
            }
        }

        logger.debug("map: {}", map);

        // Second, handle each page impact
        for (Entry<Page, Impact> entry : map.entrySet()) {
            final Page page = entry.getKey();
            final Impact impact = entry.getValue();
            doProcessPage(page, impact);
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

    //-------------//
    // processPage //
    //-------------//
    public void processPage (Page page)
    {
        doProcessPage(page, WHOLE_IMPACT);
    }

    //--------------//
    // refineLyrics //
    //--------------//
    /**
     * Refine syllables across systems in page
     *
     * @param page provided page
     */
    private void refineLyrics (Page page)
    {
        for (SystemInfo system : page.getSystems()) {
            for (Inter inter : system.getSig().inters(LyricLineInter.class)) {
                final LyricLineInter line = (LyricLineInter) inter;
                line.refineLyricSyllables();
            }
        }
    }

    //~ Static Methods -----------------------------------------------------------------------------

    //-----------//
    // getImpact //
    //-----------//
    private static Impact getImpact (Map<Page, Impact> map,
                                     Page page)
    {
        Impact impact = map.get(page);

        if (impact == null) {
            map.put(page, impact = new Impact());
        }

        return impact;
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //--------//
    // Impact //
    //--------//
    private static class Impact
    {
        boolean onParts = false;

        boolean onSlurs = false;

        boolean onLyrics = false;

        boolean onVoices = false;

        boolean onMeasures = false;

        public Impact ()
        {
        }

        public Impact (boolean onParts,
                       boolean onSlurs,
                       boolean onLyrics,
                       boolean onVoices,
                       boolean onMeasures)
        {
            this.onParts = onParts;
            this.onSlurs = onSlurs;
            this.onLyrics = onLyrics;
            this.onVoices = onVoices;
            this.onMeasures = onMeasures;
        }

        @Override
        public String toString ()
        {
            return new StringBuilder("PageImpact{") //
                    .append("parts:").append(onParts) //
                    .append(" slurs:").append(onSlurs) //
                    .append(" lyrics:").append(onLyrics) //
                    .append(" voices:").append(onVoices) //
                    .append(" measures:").append(onMeasures) //
                    .append("}").toString();
        }
    }
}
