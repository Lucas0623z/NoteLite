#! /bin/bash

if [ $# -ne 2 ]; then
echo "Error in usage: $./MIDIToMIDIAlign.sh ref(.mid) align(.mid)"
exit 1
fi

I1=$1
I2=$2

ProgramFolder="./Programs"
RelCurrentFolder="."

$ProgramFolder/midi2pianoroll 0 $RelCurrentFolder/${I1}
$ProgramFolder/midi2pianoroll 0 $RelCurrentFolder/${I2}

$ProgramFolder/SprToFmt3x $RelCurrentFolder/${I1}_spr.txt $RelCurrentFolder/${I1}_fmt3x.txt
$ProgramFolder/Fmt3xToHmm $RelCurrentFolder/${I1}_fmt3x.txt $RelCurrentFolder/${I1}_hmm.txt

$ProgramFolder/ScorePerfmMatcher $RelCurrentFolder/${I1}_hmm.txt $RelCurrentFolder/${I2}_spr.txt $RelCurrentFolder/${I2}_pre_match.txt 0.001
$ProgramFolder/ErrorDetection $RelCurrentFolder/${I1}_fmt3x.txt $RelCurrentFolder/${I1}_hmm.txt $RelCurrentFolder/${I2}_pre_match.txt $RelCurrentFolder/${I2}_err_match.txt 0
$ProgramFolder/RealignmentMOHMM $RelCurrentFolder/${I1}_fmt3x.txt $RelCurrentFolder/${I1}_hmm.txt $RelCurrentFolder/${I2}_err_match.txt $RelCurrentFolder/${I2}_realigned_match.txt 0.3

cp $RelCurrentFolder/${I2}_realigned_match.txt $RelCurrentFolder/${I2}_match.txt
$ProgramFolder/MatchToCorresp $RelCurrentFolder/${I2}_match.txt $RelCurrentFolder/${I1}_spr.txt $RelCurrentFolder/${I2}_corresp.txt

rm $RelCurrentFolder/${I2}_realigned_match.txt
rm $RelCurrentFolder/${I2}_err_match.txt
rm $RelCurrentFolder/${I2}_pre_match.txt

