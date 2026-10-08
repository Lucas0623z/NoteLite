/*
Copyright 2019 Eita Nakamura

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/
#include<fstream>
#include<iostream>
#include<cmath>
#include<string>
#include<sstream>
#include<vector>
#include<algorithm>
#include"stdio.h"
#include"stdlib.h"
#include"ScoreFollower_v170503.hpp"
using namespace std;

int main(int argc, char** argv){
	vector<int> v(100);
	vector<double> d(100);
	vector<string> s(100);
	stringstream ss;
	clock_t start, end;
	start = clock();

	if(argc!=5){
		cout<<"Error in usage: $./ScorePerfmMatcher hmm.txt perfm_spr.txt result_match.txt secPerQuarterNote(=0.01)"<<endl;
		return -1;
	}//endif
	string hmmName=string(argv[1]);
	string perfmName=string(argv[2]);
	string matchfileName=string(argv[3]);
	double secPerQN=atof(argv[4]);

	ScoreFollower scofo(hmmName,secPerQN);

	PianoRoll pr;
	pr.ReadFileSpr(perfmName);

	ScorePerfmMatch match;
	match=scofo.GetMatchResult(pr);

	match.comments.push_back(" Score: "+hmmName);
	match.comments.push_back(" Perfm: "+perfmName);

	match.WriteFile(matchfileName);

//	end = clock(); cout<<"Elapsed time : "<<((double)(end - start) / CLOCKS_PER_SEC)<<" sec"<<endl; start=end;
	return 0;
}//end main

