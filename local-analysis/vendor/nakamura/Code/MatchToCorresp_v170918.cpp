/*
Copyright 2019 Eita Nakamura

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/
#include<iostream>
#include<string>
#include<sstream>
#include<algorithm>
#include<cmath>
#include<vector>
#include<fstream>
#include<cassert>
#include"ScorePerfmMatch_v170503.hpp"
#include"PianoRoll_v170503.hpp"
using namespace std;

class CorrespEvt{
public:
	string refID;
	double refOntime;
	string refSitch;
	int refPitch;
	int refOnvel;
	string alignID;
	double alignOntime;
	string alignSitch;
	int alignPitch;
	int alignOnvel;
};//endclass CorrespEvt


int main(int argc, char** argv) {

	vector<int> v(100);
	vector<double> d(100);
	vector<string> s(100);
	stringstream ss;

	if(argc!=4){cout<<"Error in usage! : $./this align_match.txt ref_spr.txt out_corresp.txt"<<endl; return -1;}

	string alignMatch=string(argv[1]);
	string refSpr=string(argv[2]);
	string outCorresp=string(argv[3]);

	ScorePerfmMatch match;
	PianoRoll pr;

	match.ReadFile(alignMatch);
	pr.ReadFileSpr(refSpr);

	vector<CorrespEvt> corresp;
	CorrespEvt evt;
	for(int n=0;n<match.evts.size();n+=1){
		evt.alignID=match.evts[n].ID;
		evt.alignOntime=match.evts[n].ontime;
		evt.alignSitch=match.evts[n].sitch;
		evt.alignPitch=SitchToPitch(match.evts[n].sitch);
		evt.alignOnvel=match.evts[n].onvel;
		evt.refID="*";
		evt.refOntime=-1;
		evt.refSitch="*";
		evt.refPitch=-1;
		evt.refOnvel=-1;
		if(match.evts[n].errorInd<2){
			evt.refID=match.evts[n].fmt1ID.substr(match.evts[n].fmt1ID.rfind("-")+1);
			for(int m=0;m<pr.evts.size();m+=1){
				if(pr.evts[m].ID==evt.refID){
					evt.refOntime=pr.evts[m].ontime;
					evt.refSitch=pr.evts[m].sitch;
					evt.refPitch=pr.evts[m].pitch;
					evt.refOnvel=pr.evts[m].onvel;
					break;
				}//endif
			}//endfor m
		}//endif
		corresp.push_back(evt);
	}//endfor n

	for(int i=0;i<match.missingNotes.size();i+=1){
		evt.alignID="*";
		evt.alignOntime=-1;
		evt.alignSitch="*";
		evt.alignPitch=-1;
		evt.alignOnvel=-1;
		evt.refID=match.missingNotes[i].fmt1ID.substr(match.missingNotes[i].fmt1ID.rfind("-")+1);
		evt.refOntime=-1;
		evt.refSitch="*";
		evt.refPitch=-1;
		evt.refOnvel=-1;
		for(int m=0;m<pr.evts.size();m+=1){
			if(pr.evts[m].ID==evt.refID){
				evt.refOntime=pr.evts[m].ontime;
				evt.refSitch=pr.evts[m].sitch;
				evt.refPitch=pr.evts[m].pitch;
				evt.refOnvel=pr.evts[m].onvel;
				break;
			}//endif
		}//endfor m
		corresp.push_back(evt);
	}//endfor i

	ofstream ofs(outCorresp.c_str());
ofs<<"// alignID alignOntime alignSitch alignPitch alignOnvel refID refOntime refSitch refPitch refOnvel\n";
	for(int i=0;i<corresp.size();i+=1){
		if(corresp[i].alignID=="*"){
ofs<<"*\t-1\t*\t-1\t-1\t";
		}else{
ofs<<corresp[i].alignID<<"\t"<<fixed<<setprecision(6)<<corresp[i].alignOntime<<"\t"<<corresp[i].alignSitch<<"\t"<<corresp[i].alignPitch<<"\t"<<corresp[i].alignOnvel<<"\t";
		}//endif
		if(corresp[i].refID=="*"){
ofs<<"*\t-1\t*\t-1\t-1\t";
		}else{
ofs<<corresp[i].refID<<"\t"<<fixed<<setprecision(6)<<corresp[i].refOntime<<"\t"<<corresp[i].refSitch<<"\t"<<corresp[i].refPitch<<"\t"<<corresp[i].refOnvel<<"\t";
		}//endif
ofs<<"\n";
	}//endfor i
	ofs.close();

	return 0;
}//end main
