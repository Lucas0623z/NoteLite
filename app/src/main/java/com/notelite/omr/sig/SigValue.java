//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                         S i g V a l u e                                        //
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
package com.notelite.omr.sig;

import com.notelite.omr.sheet.Sheet;
import com.notelite.omr.sheet.Staff;
import com.notelite.omr.sheet.StaffManager;
import com.notelite.omr.sig.inter.AbstractInter;
import com.notelite.omr.sig.inter.AlterInter;
import com.notelite.omr.sig.inter.ArpeggiatoInter;
import com.notelite.omr.sig.inter.ArticulationInter;
import com.notelite.omr.sig.inter.AugmentationDotInter;
import com.notelite.omr.sig.inter.BarConnectorInter;
import com.notelite.omr.sig.inter.BarlineInter;
import com.notelite.omr.sig.inter.BeamGroupInter;
import com.notelite.omr.sig.inter.BeamHookInter;
import com.notelite.omr.sig.inter.BeamInter;
import com.notelite.omr.sig.inter.BeatUnitInter;
import com.notelite.omr.sig.inter.BowInter;
import com.notelite.omr.sig.inter.BraceInter;
import com.notelite.omr.sig.inter.BracketConnectorInter;
import com.notelite.omr.sig.inter.BracketInter;
import com.notelite.omr.sig.inter.BreathMarkInter;
import com.notelite.omr.sig.inter.CaesuraInter;
import com.notelite.omr.sig.inter.ChordNameInter;
import com.notelite.omr.sig.inter.ClefInter;
import com.notelite.omr.sig.inter.ClutterInter;
import com.notelite.omr.sig.inter.DynamicsInter;
import com.notelite.omr.sig.inter.EndingInter;
import com.notelite.omr.sig.inter.FermataArcInter;
import com.notelite.omr.sig.inter.FermataDotInter;
import com.notelite.omr.sig.inter.FermataInter;
import com.notelite.omr.sig.inter.FingeringInter;
import com.notelite.omr.sig.inter.FlagInter;
import com.notelite.omr.sig.inter.FretInter;
import com.notelite.omr.sig.inter.GraceChordInter;
import com.notelite.omr.sig.inter.GraceChordInter.HiddenHeadInter;
import com.notelite.omr.sig.inter.GraceChordInter.HiddenStemInter;
import com.notelite.omr.sig.inter.HeadChordInter;
import com.notelite.omr.sig.inter.HeadInter;
import com.notelite.omr.sig.inter.Inter;
import com.notelite.omr.sig.inter.KeyAlterInter;
import com.notelite.omr.sig.inter.KeyInter;
import com.notelite.omr.sig.inter.LedgerInter;
import com.notelite.omr.sig.inter.LyricItemInter;
import com.notelite.omr.sig.inter.LyricLineInter;
import com.notelite.omr.sig.inter.MarkerInter;
import com.notelite.omr.sig.inter.MeasureCountInter;
import com.notelite.omr.sig.inter.MeasureRepeatInter;
import com.notelite.omr.sig.inter.MetronomeInter;
import com.notelite.omr.sig.inter.MultipleRestInter;
import com.notelite.omr.sig.inter.NumberInter;
import com.notelite.omr.sig.inter.OctaveShiftInter;
import com.notelite.omr.sig.inter.OrnamentInter;
import com.notelite.omr.sig.inter.PedalInter;
import com.notelite.omr.sig.inter.PlayingInter;
import com.notelite.omr.sig.inter.PluckingInter;
import com.notelite.omr.sig.inter.RehearsalInter;
import com.notelite.omr.sig.inter.RepeatDotInter;
import com.notelite.omr.sig.inter.RestChordInter;
import com.notelite.omr.sig.inter.RestInter;
import com.notelite.omr.sig.inter.SegmentInter;
import com.notelite.omr.sig.inter.SentenceInter;
import com.notelite.omr.sig.inter.SimileMarkInter;
import com.notelite.omr.sig.inter.SlurInter;
import com.notelite.omr.sig.inter.SmallBeamInter;
import com.notelite.omr.sig.inter.SmallChordInter;
import com.notelite.omr.sig.inter.SmallFlagInter;
import com.notelite.omr.sig.inter.StaffBarlineInter;
import com.notelite.omr.sig.inter.StemInter;
import com.notelite.omr.sig.inter.TimeCustomInter;
import com.notelite.omr.sig.inter.TimeNumberInter;
import com.notelite.omr.sig.inter.TimePairInter;
import com.notelite.omr.sig.inter.TimeWholeInter;
import com.notelite.omr.sig.inter.TremoloInter;
import com.notelite.omr.sig.inter.TupletInter;
import com.notelite.omr.sig.inter.VerticalSerifInter;
import com.notelite.omr.sig.inter.WedgeInter;
import com.notelite.omr.sig.inter.WordInter;
import com.notelite.omr.sig.relation.AlterHeadRelation;
import com.notelite.omr.sig.relation.AugmentationRelation;
import com.notelite.omr.sig.relation.BarConnectionRelation;
import com.notelite.omr.sig.relation.BarGroupRelation;
import com.notelite.omr.sig.relation.BeamBeamRelation;
import com.notelite.omr.sig.relation.BeamHeadRelation;
import com.notelite.omr.sig.relation.BeamRestRelation;
import com.notelite.omr.sig.relation.BeamStemRelation;
import com.notelite.omr.sig.relation.ChordArpeggiatoRelation;
import com.notelite.omr.sig.relation.ChordArticulationRelation;
import com.notelite.omr.sig.relation.ChordBowRelation;
import com.notelite.omr.sig.relation.ChordDynamicsRelation;
import com.notelite.omr.sig.relation.ChordGraceRelation;
import com.notelite.omr.sig.relation.ChordNameRelation;
import com.notelite.omr.sig.relation.ChordOrnamentRelation;
import com.notelite.omr.sig.relation.ChordPauseRelation;
import com.notelite.omr.sig.relation.ChordPedalRelation;
import com.notelite.omr.sig.relation.ChordSentenceRelation;
import com.notelite.omr.sig.relation.ChordStemRelation;
import com.notelite.omr.sig.relation.ChordSyllableRelation;
import com.notelite.omr.sig.relation.ChordTupletRelation;
import com.notelite.omr.sig.relation.ChordWedgeRelation;
import com.notelite.omr.sig.relation.ClefKeyRelation;
import com.notelite.omr.sig.relation.Containment;
import com.notelite.omr.sig.relation.DoubleDotRelation;
import com.notelite.omr.sig.relation.EndingBarRelation;
import com.notelite.omr.sig.relation.EndingSentenceRelation;
import com.notelite.omr.sig.relation.Exclusion;
import com.notelite.omr.sig.relation.FermataBarRelation;
import com.notelite.omr.sig.relation.FermataChordRelation;
import com.notelite.omr.sig.relation.FlagStemRelation;
import com.notelite.omr.sig.relation.HeadFingeringRelation;
import com.notelite.omr.sig.relation.HeadHeadRelation;
import com.notelite.omr.sig.relation.HeadPlayingRelation;
import com.notelite.omr.sig.relation.HeadPluckingRelation;
import com.notelite.omr.sig.relation.HeadStemRelation;
import com.notelite.omr.sig.relation.KeyAltersRelation;
import com.notelite.omr.sig.relation.MarkerBarRelation;
import com.notelite.omr.sig.relation.MeasureRepeatCountRelation;
import com.notelite.omr.sig.relation.MirrorRelation;
import com.notelite.omr.sig.relation.MultipleRestCountRelation;
import com.notelite.omr.sig.relation.MultipleRestSerifRelation;
import com.notelite.omr.sig.relation.NextInVoiceRelation;
import com.notelite.omr.sig.relation.NoExclusion;
import com.notelite.omr.sig.relation.OctaveShiftChordRelation;
import com.notelite.omr.sig.relation.Relation;
import com.notelite.omr.sig.relation.RepeatDotBarRelation;
import com.notelite.omr.sig.relation.RepeatDotPairRelation;
import com.notelite.omr.sig.relation.SameTimeRelation;
import com.notelite.omr.sig.relation.SeparateTimeRelation;
import com.notelite.omr.sig.relation.SeparateVoiceRelation;
import com.notelite.omr.sig.relation.SlurHeadRelation;
import com.notelite.omr.sig.relation.StemAlignmentRelation;
import com.notelite.omr.sig.relation.TimeTopBottomRelation;
import com.notelite.omr.sig.relation.TremoloStemRelation;
import com.notelite.omr.sig.relation.TremoloWholeRelation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;

import javax.xml.bind.annotation.XmlAccessType;
import javax.xml.bind.annotation.XmlAccessorType;
import javax.xml.bind.annotation.XmlAttribute;
import javax.xml.bind.annotation.XmlElement;
import javax.xml.bind.annotation.XmlElementRef;
import javax.xml.bind.annotation.XmlElementRefs;
import javax.xml.bind.annotation.XmlElementWrapper;
import javax.xml.bind.annotation.XmlRootElement;
import javax.xml.bind.annotation.adapters.XmlAdapter;

/**
 * Class <code>SigValue</code> represents the content of a SIG for use by JAXB.
 * <p>
 * All Inter instances are defined within their containing SIG.
 * If referred from outside SIG, they are handled via XmlIDREF's.
 *
 * @author NoteLite Contributors
 */
@XmlRootElement(name = "sig")
@XmlAccessorType(XmlAccessType.NONE)
public class SigValue
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(SigValue.class);

    //~ Instance fields ----------------------------------------------------------------------------

    // NOTA: For easier review, class names here below should be listed alphabetically.
    /**
     * All CONCRETE inters found in sig are gathered here as true defs.
     * <br>
     * No abstract!
     */
    @SuppressWarnings("deprecation")
    @XmlElementWrapper(name = "inters")
    @XmlElementRefs({
    // @formatter:off
            @XmlElementRef(type = AlterInter.class),
            @XmlElementRef(type = AugmentationDotInter.class),
            @XmlElementRef(type = ArpeggiatoInter.class),
            @XmlElementRef(type = ArticulationInter.class),
            @XmlElementRef(type = BarConnectorInter.class),
            @XmlElementRef(type = BarlineInter.class),
            @XmlElementRef(type = BeamGroupInter.class),
            @XmlElementRef(type = BeamHookInter.class),
            @XmlElementRef(type = BeamInter.class),
            @XmlElementRef(type = BowInter.class),
            @XmlElementRef(type = BraceInter.class),
            @XmlElementRef(type = BracketConnectorInter.class),
            @XmlElementRef(type = BracketInter.class),
            @XmlElementRef(type = BreathMarkInter.class),
            @XmlElementRef(type = CaesuraInter.class),
            @XmlElementRef(type = ChordNameInter.class),
            @XmlElementRef(type = ClefInter.class),
            @XmlElementRef(type = ClutterInter.class),
            @XmlElementRef(type = DynamicsInter.class),
            @XmlElementRef(type = EndingInter.class),
            @XmlElementRef(type = FermataDotInter.class),
            @XmlElementRef(type = FermataArcInter.class),
            @XmlElementRef(type = FermataInter.class),
            @XmlElementRef(type = FingeringInter.class),
            @XmlElementRef(type = FlagInter.class),
            @XmlElementRef(type = FretInter.class),
            @XmlElementRef(type = GraceChordInter.class),
            @XmlElementRef(type = HeadChordInter.class),
            @XmlElementRef(type = HeadInter.class),
            @XmlElementRef(type = HiddenHeadInter.class),
            @XmlElementRef(type = HiddenStemInter.class),
            @XmlElementRef(type = KeyAlterInter.class),
            @XmlElementRef(type = KeyInter.class),
            @XmlElementRef(type = LedgerInter.class),
            @XmlElementRef(type = LyricItemInter.class),
            @XmlElementRef(type = LyricLineInter.class),
            @XmlElementRef(type = MarkerInter.class),
            @XmlElementRef(type = MeasureCountInter.class),
            @XmlElementRef(type = MeasureRepeatInter.class),
            @XmlElementRef(type = MultipleRestInter.class),
            @XmlElementRef(type = NumberInter.class),
            @XmlElementRef(type = OctaveShiftInter.class),
            @XmlElementRef(type = OrnamentInter.class),
            @XmlElementRef(type = PedalInter.class),
            @XmlElementRef(type = PlayingInter.class),
            @XmlElementRef(type = PluckingInter.class),
            @XmlElementRef(type = RehearsalInter.class),
            @XmlElementRef(type = RepeatDotInter.class),
            @XmlElementRef(type = RestChordInter.class),
            @XmlElementRef(type = RestInter.class),
            @XmlElementRef(type = SegmentInter.class),
            @XmlElementRef(type = SentenceInter.class),
            @XmlElementRef(type = SimileMarkInter.class), // Temporarily...
            @XmlElementRef(type = SlurInter.class),
            @XmlElementRef(type = SmallBeamInter.class),
            @XmlElementRef(type = SmallChordInter.class),
            @XmlElementRef(type = SmallFlagInter.class),
            @XmlElementRef(type = StaffBarlineInter.class),
            @XmlElementRef(type = StemInter.class),
            @XmlElementRef(type = MetronomeInter.class),
            @XmlElementRef(type = BeatUnitInter.class),
            @XmlElementRef(type = TimeCustomInter.class),
            @XmlElementRef(type = TimeNumberInter.class),
            @XmlElementRef(type = TimePairInter.class),
            @XmlElementRef(type = TimeWholeInter.class),
            @XmlElementRef(type = TremoloInter.class),
            @XmlElementRef(type = TupletInter.class),
            @XmlElementRef(type = VerticalSerifInter.class),
            @XmlElementRef(type = WedgeInter.class),
            @XmlElementRef(type = WordInter.class) })
    // @formatter:on
    private final ArrayList<AbstractInter> inters = new ArrayList<>();

    /** Sig edges: relations between inters. */
    @XmlElementWrapper(name = "relations")
    @XmlElement(name = "relation")
    private final ArrayList<RelationValue> relations = new ArrayList<>();

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * No-argument constructor meant for JAXB.
     */
    public SigValue ()
    {
    }

    //~ Methods ------------------------------------------------------------------------------------

    /**
     * Method to be called only when SigValue IDREFs have been fully unmarshalled,
     * to populate the target SIG.
     *
     * @param sig the (rather empty) sig to be completed
     */
    public void populateSig (SIGraph sig)
    {
        final Sheet sheet = sig.getSystem().getSheet();
        final StaffManager mgr = sheet.getStaffManager();
        final InterIndex index = sheet.getInterIndex();

        // Populate inters
        sig.populateAllInters(inters);

        for (Inter inter : sig.vertexSet()) {
            inter.setSig(sig);
            index.insert(inter);
        }

        // Populate relations
        for (RelationValue rel : relations) {
            try {
                Inter source = index.getEntity(rel.sourceId);
                Inter target = index.getEntity(rel.targetId);
                sig.addEdge(source, target, rel.relation);
            } catch (Throwable ex) {
                logger.error("Error unmarshalling relation " + rel + " ex:" + ex, ex);
            }
        }

        // Replace StaffHolder instances with real Staff instances
        for (Inter inter : inters) {
            Staff.StaffHolder.checkStaffHolder(inter, mgr);
        }
    }

    @Override
    public String toString ()
    {
        return new StringBuilder("SigValue{") //
                .append("inters:").append(inters.size()) //
                .append(" relations:").append(relations.size()) //
                .append('}').toString();
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-------------//
    // JaxbAdapter //
    //-------------//
    /**
     * Meant for JAXB handling of SIG.
     */
    public static class JaxbAdapter
            extends XmlAdapter<SigValue, SIGraph>
    {
        /**
         * Generate a SigValue out of the existing SIG.
         *
         * @param sig the existing SIG whose content is to be stored into a SigValue
         * @return the generated SigValue instance
         * @throws Exception if something goes wrong
         */
        @Override
        public SigValue marshal (SIGraph sig)
            throws Exception
        {
            SigValue sigValue = new SigValue();

            for (Inter inter : sig.vertexSet()) {
                AbstractInter abstractInter = (AbstractInter) inter;
                sigValue.inters.add(abstractInter);
            }

            for (Relation edge : sig.edgeSet()) {
                sigValue.relations.add(
                        new RelationValue(sig.getEdgeSource(edge), sig.getEdgeTarget(edge), edge));
            }

            return sigValue;
        }

        /**
         * Generate a (rather empty) SIG from this SigValue
         *
         * @param sigValue the value to be converted
         * @return a new SIG instance, to be later populated via {@link #populateSig}
         * @throws Exception if something goes wrong
         */
        @Override
        public SIGraph unmarshal (SigValue sigValue)
            throws Exception
        {
            return new SIGraph(sigValue);
        }
    }

    //---------------//
    // RelationValue //
    //---------------//
    /**
     * Class <code>RelationValue</code> represents the JAXB-compatible content of a
     * relation established between two inters.
     */
    private static class RelationValue
    {
        /** Inter ID for the relation source. */
        @XmlAttribute(name = "source")
        public int sourceId;

        /** Inter ID for the relation target. */
        @XmlAttribute(name = "target")
        public int targetId;

        /**
         * The relation instance.
         * <p>
         * Here we list alphabetically all CONCRETE relation types. No abstract!
         */
        @XmlElementRefs({ //
                @XmlElementRef(type = AlterHeadRelation.class),
                @XmlElementRef(type = AugmentationRelation.class),
                @XmlElementRef(type = BarConnectionRelation.class),
                @XmlElementRef(type = BarGroupRelation.class),
                @XmlElementRef(type = BeamBeamRelation.class),
                @XmlElementRef(type = BeamHeadRelation.class),
                @XmlElementRef(type = BeamRestRelation.class),
                @XmlElementRef(type = BeamStemRelation.class),
                @XmlElementRef(type = ChordArpeggiatoRelation.class),
                @XmlElementRef(type = ChordArticulationRelation.class),
                @XmlElementRef(type = ChordBowRelation.class),
                @XmlElementRef(type = ChordDynamicsRelation.class),
                @XmlElementRef(type = ChordGraceRelation.class),
                @XmlElementRef(type = ChordNameRelation.class),
                @XmlElementRef(type = ChordOrnamentRelation.class),
                @XmlElementRef(type = ChordPauseRelation.class),
                @XmlElementRef(type = ChordPedalRelation.class),
                @XmlElementRef(type = ChordSentenceRelation.class),
                @XmlElementRef(type = ChordStemRelation.class),
                @XmlElementRef(type = ChordSyllableRelation.class),
                @XmlElementRef(type = ChordTupletRelation.class),
                @XmlElementRef(type = ChordWedgeRelation.class),
                @XmlElementRef(type = ClefKeyRelation.class),
                @XmlElementRef(type = Containment.class),
                @XmlElementRef(type = DoubleDotRelation.class),
                @XmlElementRef(type = EndingBarRelation.class),
                @XmlElementRef(type = EndingSentenceRelation.class),
                @XmlElementRef(type = Exclusion.class),
                @XmlElementRef(type = FermataBarRelation.class),
                @XmlElementRef(type = FermataChordRelation.class),
                @XmlElementRef(type = FlagStemRelation.class),
                @XmlElementRef(type = HeadFingeringRelation.class),
                @XmlElementRef(type = HeadHeadRelation.class),
                @XmlElementRef(type = HeadPlayingRelation.class),
                @XmlElementRef(type = HeadPluckingRelation.class),
                @XmlElementRef(type = HeadStemRelation.class),
                @XmlElementRef(type = KeyAltersRelation.class),
                @XmlElementRef(type = MarkerBarRelation.class),
                @XmlElementRef(type = MirrorRelation.class),
                @XmlElementRef(type = MultipleRestCountRelation.class),
                @XmlElementRef(type = MultipleRestSerifRelation.class),
                @XmlElementRef(type = NextInVoiceRelation.class),
                @XmlElementRef(type = NoExclusion.class),
                @XmlElementRef(type = OctaveShiftChordRelation.class),
                @XmlElementRef(type = RepeatDotBarRelation.class),
                @XmlElementRef(type = RepeatDotPairRelation.class),
                @XmlElementRef(type = SameTimeRelation.class),
                @XmlElementRef(type = SeparateTimeRelation.class),
                @XmlElementRef(type = SeparateVoiceRelation.class),
                @XmlElementRef(type = MeasureRepeatCountRelation.class),
                @XmlElementRef(type = SlurHeadRelation.class),
                @XmlElementRef(type = StemAlignmentRelation.class),
                @XmlElementRef(type = TimeTopBottomRelation.class),
                @XmlElementRef(type = TremoloStemRelation.class),
                @XmlElementRef(type = TremoloWholeRelation.class) })
        public Relation relation;

        /**
         * No-argument constructor meant for JAXB.
         */
        private RelationValue ()
        {
        }

        /**
         * Creates a new <code>RelationValue</code> object.
         *
         * @param source   source inter
         * @param target   target inter
         * @param relation relation from source to target
         */
        RelationValue (Inter source,
                       Inter target,
                       Relation relation)
        {
            this.sourceId = source.getId();
            this.targetId = target.getId();
            this.relation = relation;
        }

        @Override
        public String toString ()
        {
            return new StringBuilder("RelationValue{") //
                    .append("src:").append(sourceId) //
                    .append(" tgt:").append(targetId) //
                    .append(" rel:").append(relation) //
                    .append('}').toString();
        }
    }
}
