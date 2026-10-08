/*
Copyright 2019 Eita Nakamura

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/
#ifndef SCOREPERFMMATCH_HPP
#define SCOREPERFMMATCH_HPP

#include<iostream>
#include<fstream>
#include<string>
#include<sstream>
#include<vector>
#include<stdio.h>
#include<stdlib.h>
#include<cmath>
#include<iomanip>
#include<cassert>
#include<algorithm>

#define printOn false

using namespace std;

class ScorePerfmMatchEvt{
public:
	string ID;
	double ontime;
	double offtime;
	string sitch;
	int onvel;
	int offvel;
	int channel;
	int matchStatus;//0(with corresponding score time)/1(without corresponding score time; atemporal event)/-1(note match if errorInd=2,3)
	int stime;
	string fmt1ID;
	int errorInd;//0(correct)/1(pitch error)/2(note-wise extra note, &)/3(cluster-wise extra note, *)
	string skipInd;//0(beginning)/1(resumption point)/- or +(otherwise)

	ScorePerfmMatchEvt(){}//end ScorePerfmMatchEvt
	~ScorePerfmMatchEvt(){}//end ~ScorePerfmMatchEvt

};//end class ScorePerfmMatchEvt

class MissingNote{
public:

	int stime;
	string fmt1ID;

	MissingNote(){}//end MissingNote
	~MissingNote(){}//end ~MissingNote

};//end class MissingNote

class ScorePerfmMatch{
public:
	vector<string> comments;
	vector<ScorePerfmMatchEvt> evts;
	vector<MissingNote> missingNotes;
	string version;

	ScorePerfmMatch(){}//end ScorePerfmMatch
	ScorePerfmMatch(ScorePerfmMatch const &match){
		comments=match.comments;
		evts=match.evts;
		missingNotes=match.missingNotes;
	}//end ScorePerfmMatch
	~ScorePerfmMatch(){}//end ~ScorePerfmMatch

	void ReadFile(string inputFile){
		comments.clear();
		evts.clear();
		missingNotes.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		ScorePerfmMatchEvt evt;

		ifstream ifs(inputFile.c_str());
		if(!ifs.is_open()){cout<<"File not found: "<<inputFile<<endl; assert(false);}
		while(ifs>>s[0]){
			if(s[0][0]=='/'){
				if(s[0]=="//Version:"){
					ifs>>s[1];
					if(s[1]!="ScorePerfmMatch_v170503"){
if(printOn){
						cout<<"Warning: File version is not ScorePerfmMatch_v170503: "<<s[1]<<endl;
						cout<<"Warning: File version will be replcaed when saved"<<endl;
}//endif
					}//endif
					getline(ifs,s[99]); continue;
				}else if(s[0].find("Missing")!=string::npos){
					MissingNote missingNote;
					ifs>>missingNote.stime>>missingNote.fmt1ID;
					missingNotes.push_back(missingNote);
					getline(ifs,s[99]); continue;
				}//endif
				getline(ifs,s[99]);
				comments.push_back(s[99]);
				continue;
			}else if(s[0][0]=='#'){
				getline(ifs,s[99]);
				continue;
			}//endif
			evt.ID=s[0];
			ifs>>evt.ontime>>evt.offtime>>evt.sitch>>evt.onvel>>evt.offvel>>evt.channel;
			ifs>>evt.matchStatus>>evt.stime>>evt.fmt1ID>>evt.errorInd>>evt.skipInd;
			evts.push_back(evt);
			getline(ifs,s[99]);
		}//endwhile
		ifs.close();
	}//end ReadFile

	void ReadOldMissingNotes(string inputFile){
		missingNotes.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		ScorePerfmMatchEvt evt;

		ifstream ifs(inputFile.c_str());
		if(!ifs.is_open()){cout<<"File not found: "<<inputFile<<endl; assert(false);}
		while(ifs>>s[0]){
			if(s[0][0]=='#'){
				ifs>>s[1];
				if(s[1]=="missing"){
					MissingNote missingNote;
					ifs>>missingNote.stime>>missingNote.fmt1ID;
					missingNotes.push_back(missingNote);
					getline(ifs,s[99]); continue;
				}//endif
				getline(ifs,s[99]); continue;
			}//endif
			getline(ifs,s[99]);
		}//endwhile
		ifs.close();
	}//end ReadOldMissingNotes

	void WriteFile(string outputFile){
		ofstream ofs(outputFile.c_str());
		ofs<<"//Version: ScorePerfmMatch_v170503\n";
		for(int i=0;i<comments.size();i+=1){
			ofs<<"//"<<comments[i]<<"\n";
		}//endfor i
		for(int n=0;n<evts.size();n+=1){
			ScorePerfmMatchEvt evt=evts[n];
			ofs<<evt.ID<<"\t"<<fixed<<setprecision(6)<<evt.ontime<<"\t"<<evt.offtime<<"\t"<<evt.sitch<<"\t"<<evt.onvel<<"\t"<<evt.offvel<<"\t"<<evt.channel<<"\t";
			ofs<<evt.matchStatus<<"\t"<<evt.stime<<"\t"<<evt.fmt1ID<<"\t"<<evt.errorInd<<"\t"<<evt.skipInd<<"\n";
		}//endfor n
		for(int i=0;i<missingNotes.size();i+=1){
			ofs<<"//Missing "<<missingNotes[i].stime<<"\t"<<missingNotes[i].fmt1ID<<"\n";
		}//endfor i
		ofs.close();
	}//end WriteFile

};//end class ScorePerfmMatch

#endif // SCOREPERFMMATCH_HPP

