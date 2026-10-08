#! /bin/bash

ProgramFolder="./Programs"
CodeFolder="./Code"

mkdir $ProgramFolder

g++ -O2 $CodeFolder/ErrorDetection_v190702.cpp -o $ProgramFolder/ErrorDetection
g++ -O2 $CodeFolder/RealignmentMOHMM_v170427.cpp -o $ProgramFolder/RealignmentMOHMM
g++ -O2 $CodeFolder/ScorePerfmMatcher_v170101_2.cpp -o $ProgramFolder/ScorePerfmMatcher
g++ -O2 $CodeFolder/midi2pianoroll_v170504.cpp -o $ProgramFolder/midi2pianoroll
g++ -O2 $CodeFolder/MusicXMLToFmt3x_v170104.cpp -o $ProgramFolder/MusicXMLToFmt3x
g++ -O2 $CodeFolder/MusicXMLToHMM_v170104.cpp -o $ProgramFolder/MusicXMLToHMM
g++ -O2 $CodeFolder/SprToFmt3x_v170225.cpp -o $ProgramFolder/SprToFmt3x
g++ -O2 $CodeFolder/Fmt3xToHmm_v170225.cpp -o $ProgramFolder/Fmt3xToHmm
g++ -O2 $CodeFolder/MatchToCorresp_v170918.cpp -o $ProgramFolder/MatchToCorresp

