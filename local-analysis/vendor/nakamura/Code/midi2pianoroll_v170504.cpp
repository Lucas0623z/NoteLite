/*
Copyright 2019 Eita Nakamura

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/
//g++ -O2 -I/Users/eita/boost_1_63_0 -I/Users/eita/Dropbox/Research/Tool/All/ midi2pianoroll_v170504.cpp -o midi2pianoroll
#include<iostream>
#include<iomanip>
#include<fstream>
#include<string>
#include<sstream>
#include<vector>
#include<stdio.h>
#include<stdlib.h>
#include<cmath>
#include<cassert>
#include<algorithm>
#include "PianoRoll_v170503.hpp"
using namespace std;

int main(int argc, char** argv) {
	vector<int> v(100);
	vector<double> d(100);
	vector<string> s(100);
	stringstream ss;

	if(argc!=3){cout<<"Error in usage: $./this (0:spr/1:ipr/2:spr[pedal on]/3:ipr[pedal on]) in(.mid)"<<endl; return -1;}
		string infileStem=string(argv[2]);
		int pianoRollType=atoi(argv[1]);//0: spelled pitch, 1: integral pitch
		if(pianoRollType<0 || pianoRollType>3){
		cout<<"Error in usage: $./this (0:spr/1:ipr/2:spr[pedal on]/3:ipr[pedal on]) in(.mid)"<<endl; return -1;
	}//endif

	PianoRoll pr;
	ss.str(""); ss<<infileStem<<".mid";
	pr.ReadMIDIFile(ss.str());

	if(pianoRollType==0||pianoRollType==2){
		ss.str(""); ss<<infileStem<<"_spr.txt";
		pr.WriteFileSpr(ss.str(),(pianoRollType==2));
	}else if(pianoRollType==1||pianoRollType==3){
		ss.str(""); ss<<infileStem<<"_ipr.txt";
		pr.WriteFileIpr(ss.str(),(pianoRollType==3));
	}//endif

  return 0;
}//end main


