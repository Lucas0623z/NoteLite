/*
Copyright 2019 Eita Nakamura

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/
#ifndef FMT3X_HPP
#define FMT3X_HPP

#include<iostream>
#include<fstream>
#include<string>
#include<sstream>
#include<vector>
#include<stdio.h>
#include<stdlib.h>
#include<cmath>
#include<cassert>
#include<algorithm>
#include"Fmt1x_v170108_2.hpp"
#include"BasicPitchCalculation_v170101.hpp"
#include"PianoRoll_v170503.hpp"

using namespace std;

class Fmt3xEvt{
public:
	int stime;
	string barnum;
	int staff;
	int voice;//Note: different from xml-voice.
	int subvoice;
	int subOrder;
	string eventtype;
	int dur;
	int numNotes;//=sitches.size()
	vector<string> sitches;//sitch content
	vector<string> notetypes;//N or Tr etc.
	vector<string> fmt1IDs;//id in fmt1
	vector<string> AFInfo;//information on arpeggio and fermata. Used only internally (not written in fmt3x files).
};//endclass Fmt3xEvt

class LessFmt3xEvt{
public:
	bool operator()(const Fmt3xEvt& a, const Fmt3xEvt& b){
		if(a.stime < b.stime){
			return true;
		}else if(a.stime==b.stime){
			if(a.voice<b.voice){
				return true;
			}else if(a.voice>b.voice){
				return false;
			}else if(a.subvoice<b.subvoice){
				return true;
			}else{
				return false;
			}//endif
		}else{//if a.stime > b.stime
			return false;
		}//endif
	}//end operator()

};//end class LessFmt3xEvt
//stable_sort(Fmt3xEvts.begin(), Fmt3xEvts.end(), LessFmt3xEvt());

class DuplicateOnsetEvtInFmt3x{
public:
	int stime;
	string sitch;
	int numOnsets;
	vector<string> fmt1IDs;
};//endclass DuplicateOnsetEvtInFmt3x

class VoiceInfo{//Voice 0(voiceID) 1(part) 1(xml-voice)" etc. Note: Voice can cross staffs in musicXML
public:
	int ID;
	int part;
	int voice_xml;
};//endclass VoiceInfo

class SubVoice{
public:
	vector<int> status;//-1: nothing, 0: onset, 1: tied from previous
	vector<vector<vector<int> > > poses;//posses[][][0,1]=i,j <-> fmt1x.evts[i].sitches[j]
};//endclass SubVoice

class SubVoiceStructure{
public:
	vector<SubVoice> subVoices;
	vector<int> durations;

	void Update(int pos1,int pos2,vector<int> noteStatus){
		int  accommodatingVoice=-1;
		if(subVoices.size()==0){
		}else{
			assert(subVoices[0].status.size()==noteStatus.size());
			for(int vv=0;vv<subVoices.size();vv+=1){
				bool accommodatesAllFree=true;
				bool accommodatesAllMatch=true;
				for(int i=0;i<noteStatus.size();i+=1){
					if(noteStatus[i]==-1){continue;}
					if(subVoices[vv].status[i]!=-1){
						accommodatesAllFree=false;
					}//endif
					if(subVoices[vv].status[i]!=noteStatus[i]){
						accommodatesAllMatch=false;
					}//endif
					if(i<noteStatus.size()-1){
						if(noteStatus[i+1]==-1 && subVoices[vv].status[i+1]==1){
							accommodatesAllMatch=false;
							break;
						}//endif
					}//endif
				}//endfor i
				if(accommodatesAllFree||accommodatesAllMatch){
					accommodatingVoice=vv;
					break;
				}//endif
			}//endfor vv
		}//endif

		if(accommodatingVoice<0){
			SubVoice subVoice;
			subVoice.status.assign(noteStatus.size(),-1);
			subVoice.poses.resize(noteStatus.size());
			subVoices.push_back(subVoice);
			accommodatingVoice=subVoices.size()-1;
		}//endif
		vector<int> pos(2);
		for(int i=0;i<noteStatus.size();i+=1){
			if(noteStatus[i]==-1){continue;}
			pos[0]=pos1; pos[1]=pos2;
			subVoices[accommodatingVoice].status[i]=noteStatus[i];
			subVoices[accommodatingVoice].poses[i].push_back(pos);
		}//endfor i

	}//end Update

	void Print(){
cout<<"subVoices.size() : "<<subVoices.size()<<endl;
		for(int i=0;i<subVoices.size();i+=1){
cout<<"Subvoice "<<i<<endl;
			for(int j=0;j<durations.size();j+=1){
cout<<j<<"\t"<<subVoices[i].status[j]<<"\t";
				for(int k=0;k<subVoices[i].poses[j].size();k+=1){
cout<<subVoices[i].poses[j][k][0]<<","<<subVoices[i].poses[j][k][1]<<" ";
				}//endfor k
cout<<endl;
			}//endfor j
		}//endfor i
	}//end Print

};//endclass SubVoiceStructure

class ExtendedFmt1xEvt : public Fmt1xEvt{
public:
	int new_voice;//To distinguish from voice_xml=voice;
	int subvoice;

	ExtendedFmt1xEvt(){}//end ExtendedFmt1xEvt
	ExtendedFmt1xEvt(Fmt1xEvt evt){
		stime=evt.stime;
		barnum=evt.barnum;
		part=evt.part;
		staff=evt.staff;
		voice=evt.voice;
		eventtype=evt.eventtype;
		dur=evt.dur;
		tieinfo=evt.tieinfo;
		numNotes=evt.numNotes;
		sitches=evt.sitches;
		notetypes=evt.notetypes;
		fmt1IDs=evt.fmt1IDs;
		ties=evt.ties;
		info=evt.info;
		new_voice=-1;
		subvoice=0;
	}//end ExtendedFmt1xEvt
	~ExtendedFmt1xEvt(){}//end ~ExtendedFmt1xEvt

};//endclass ExtendedFmt1xEvt

class LessExtendedFmt1xEvt{
public:
	bool operator()(const ExtendedFmt1xEvt& a, const ExtendedFmt1xEvt& b){
		if(a.stime < b.stime){
			return true;
		}else if(a.stime==b.stime){
			if(a.eventtype=="attributes"){
				return true;
			}else if(b.eventtype=="attributes"){
				return false;
			}else if(a.voice<b.voice){
				return true;
			}else if(a.voice>b.voice){
				return false;
			}else if(a.subvoice<b.subvoice){
				return true;
			}else{
				return false;
			}//endif
		}else{//if a.stime > b.stime
			return false;
		}//endif
	}//end operator()

};//end class LessExtendedFmt1xEvt
//stable_sort(ExtendedFmt1xEvts.begin(), ExtendedFmt1xEvts.end(), LessExtendedFmt1xEvt());

class ExtendedFmt1x{
public:
	vector<ExtendedFmt1xEvt> evts;

	ExtendedFmt1x(){}//end ExtendedFmt1
	ExtendedFmt1x(Fmt1x fmt1){
		for(int i=0;i<fmt1.evts.size();i+=1){
			evts.push_back(ExtendedFmt1xEvt(fmt1.evts[i]));
		}//endfor i
	}//end ExtendedFmt1
	~ExtendedFmt1x(){}//end ~ExtendedFmt1
};//endclass ExtendedFmt1x


class Fmt3x{
public:
	vector<string> comments;
	vector<Fmt3xEvt> evts;
	vector<VoiceInfo> voiceinfos;// "//Voice 0(voiceID) 1(part) 1(xml-voice)" etc.
	vector<DuplicateOnsetEvtInFmt3x> duplicateOnsets;
	int TPQN;

	void Clear(){
		comments.clear();
		evts.clear();
		voiceinfos.clear();
		duplicateOnsets.clear();
	}//end Clear

	void ReadFile(string filename){
		Clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;

		Fmt3xEvt evt;
		int l;
		ifstream ifs(filename.c_str());
		if(!ifs.is_open()){cout<<"File not found: "<<filename<<endl; assert(false);}
		while(ifs>>s[0]){
			if(s[0][0]=='/' || s[0][0]=='#'){
				if(s[0]=="//TPQN:"){
					ifs>>TPQN;
					getline(ifs,s[99]);
				}else if(s[0]=="//Fmt3xVersion:"){
					ifs>>s[1];
					if(s[1]!="170225"){
//						cout<<"Warning: The fmt3x version is not 170225!"<<endl;
					}//endif
					getline(ifs,s[99]);
				}else if(s[0]=="//DuplicateOnsets:"){
					DuplicateOnsetEvtInFmt3x dup;
					ifs>>dup.stime>>dup.sitch>>dup.numOnsets;
					for(int i=0;i<dup.numOnsets;i+=1){
						ifs>>s[1];
						dup.fmt1IDs.push_back(s[1]);
					}//endfor i
					duplicateOnsets.push_back(dup);
					getline(ifs,s[99]);
				}else{
					getline(ifs,s[99]);
					comments.push_back(s[99]);
				}//endif
				continue;
			}//endif
			evt.stime=atoi(s[0].c_str());
			ifs>>evt.barnum>>evt.staff>>evt.voice>>evt.subvoice>>evt.subOrder;
			ifs>>evt.eventtype>>evt.dur>>evt.numNotes;
			evt.sitches.clear(); evt.fmt1IDs.clear(); evt.notetypes.clear(); evt.AFInfo.clear();
			for(int j=0;j<evt.numNotes;j+=1){ifs>>s[10]; evt.sitches.push_back(s[10]);}//endfor j
			for(int j=0;j<evt.numNotes;j+=1){ifs>>s[10]; evt.notetypes.push_back(s[10]);}//endfor j
			for(int j=0;j<evt.numNotes;j+=1){ifs>>s[10]; evt.fmt1IDs.push_back(s[10]);}//endfor j
			getline(ifs,s[99]);
			evts.push_back(evt);
		}//endwhile
		ifs.close();
	}//end ReadFile

	void WriteFile(string filename){
		ofstream ofs(filename.c_str());
		ofs<<"//TPQN: "<<TPQN<<"\n";
		ofs<<"//Fmt3xVersion: 170225\n";
		for(int i=0;i<duplicateOnsets.size();i+=1){
			ofs<<"//DuplicateOnsets: "<<duplicateOnsets[i].stime<<"\t"<<duplicateOnsets[i].sitch<<"\t"<<duplicateOnsets[i].numOnsets<<"\t";
			for(int j=0;j<duplicateOnsets[i].numOnsets;j+=1){
				ofs<<duplicateOnsets[i].fmt1IDs[j]<<"\t";
			}//endfor j
			ofs<<"\n";
		}//endfor i
		for(int i=0;i<comments.size();i+=1){
			ofs<<"//"<<comments[i]<<"\n";
		}//endfor i
		for(int i=0;i<evts.size();i+=1){
			ofs<<evts[i].stime<<"\t"<<evts[i].barnum<<"\t"<<evts[i].staff<<"\t";
			ofs<<evts[i].voice<<"\t"<<evts[i].subvoice<<"\t"<<evts[i].subOrder<<"\t";
			ofs<<evts[i].eventtype<<"\t"<<evts[i].dur<<"\t"<<evts[i].numNotes<<"\t";
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].sitches[j]<<"\t";}//endfor j
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].notetypes[j]<<"\t";}//endfor j
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].fmt1IDs[j]<<"\t";}//endfor j
			ofs<<"\n";
		}//endfor i
		ofs.close();
	}//end WriteFile

	vector<string> Split(const string &str, char delim){
		istringstream iss(str); string tmp; vector<string> res;
		while(getline(iss, tmp, delim)) res.push_back(tmp);
		return res;
	}//end Split

	vector<int> FindFmt3xScorePos(string Id_fmt1,int startPos=0){
		vector<int> out(3);//Found in evts[i].fmt1IDs[j] -> out[0]=i, out[1]=j, out[2,...]=corresponding pitches
		out[0]=-1;out[1]=-1;out[2]=-1;
		for(int i=startPos;i<evts.size();i+=1){
			for(int j=0;j<evts[i].fmt1IDs.size();j+=1){
				if(evts[i].fmt1IDs[j].find(",")==string::npos){
					if(Id_fmt1==evts[i].fmt1IDs[j]){out[0]=i;out[1]=j;break;}
				}else{
					vector<string> tmp=Split(evts[i].fmt1IDs[j],',');
					for(int k=0;k<tmp.size();k+=1){
						if(Id_fmt1==tmp[k]){out[0]=i;out[1]=j;break;}//endif
					}//endfor k
				}//endif
			}//endfor j
			if(out[0]>=0){break;}
		}//endfor i
		if(out[0]>=0){
			vector<string> tmp=Split(evts[out[0]].sitches[out[1]],',');
			for(int k=0;k<tmp.size();k+=1){
				out.push_back(SitchToPitch(tmp[k]));
			}//endfor k
		}//endif
		return out;
	}//end FindFmt3xScorePos

	bool IsPitchError(string fmt1ID_,int performedPitch_){
		vector<int> scorePos=FindFmt3xScorePos(fmt1ID_);
		bool isPitchError=true;
		for(int i=2;i<scorePos.size();i+=1){
			if(performedPitch_==scorePos[i]){isPitchError=false;}
		}//endfor i
		return isPitchError;
	}//end FindFmt3xScorePos


	Fmt3x SubScore(int minStime,int maxStime){
		Fmt3x subScore;
		subScore.Clear();
		subScore.TPQN=TPQN;
		for(int n=0;n<evts.size();n+=1){
			if(evts[n].stime < minStime || evts[n].stime > maxStime){continue;}
			subScore.evts.push_back(evts[n]);
		}//endfor n
		return subScore;
	}//end SubScore

	void ConvertFromFmt1x(Fmt1x fmt1){

		Clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		TPQN=fmt1.TPQN;

		vector<vector<int> > part_voice;//part-voice. Note: Voice can cross staffs.
		ExtendedFmt1x exfmt1(fmt1);

{
		vector<int> vi(2);//part-voice;
		for(int i=0;i<exfmt1.evts.size();i+=1){
			vi[0]=exfmt1.evts[i].part;
			vi[1]=exfmt1.evts[i].voice;
			if(part_voice.size()==0 || find(part_voice.begin(),part_voice.end(),vi)==part_voice.end()){
				part_voice.push_back(vi);
			}//endif
			exfmt1.evts[i].new_voice=find(part_voice.begin(),part_voice.end(),vi)-part_voice.begin();
		}//endfor i

		VoiceInfo voiceinfo;
		for(int k=0;k<part_voice.size();k+=1){
			voiceinfo.ID=k;
			voiceinfo.part=part_voice[k][0];
			voiceinfo.voice_xml=part_voice[k][1];
			voiceinfos.push_back(voiceinfo);
		}//endfor k
}//
//cout<<"part_voice.size() : "<<part_voice.size()<<endl;

		///Reduce rests & ties
		vector<ExtendedFmt1x> exfmt1ForVoices;
		exfmt1ForVoices.resize(part_voice.size());
		for(int i=0;i<exfmt1.evts.size();i+=1){
			exfmt1ForVoices[exfmt1.evts[i].new_voice].evts.push_back(exfmt1.evts[i]);
		}//endfor i

		exfmt1.evts.clear();

		/// attributeは先に除く
		for(int ii=0;ii<part_voice.size();ii+=1){
			for(int i=exfmt1ForVoices[ii].evts.size()-1;i>=0;i-=1){
				if(exfmt1ForVoices[ii].evts[i].eventtype=="attributes"){
					exfmt1.evts.push_back(exfmt1ForVoices[ii].evts[i]);
					exfmt1ForVoices[ii].evts.erase(exfmt1ForVoices[ii].evts.begin()+i);
				}//endif
			}//endfor i
		}//endfor ii

		///Reduce rests
		for(int ii=0;ii<part_voice.size();ii+=1){
			for(int i=1;i<exfmt1ForVoices[ii].evts.size();i+=1){
				if(exfmt1ForVoices[ii].evts[i].eventtype!="rest"){continue;}
				if(exfmt1ForVoices[ii].evts[i-1].eventtype!="rest"){continue;}
				exfmt1ForVoices[ii].evts[i-1].dur+=exfmt1ForVoices[ii].evts[i].dur;
				exfmt1ForVoices[ii].evts.erase(exfmt1ForVoices[ii].evts.begin()+i);
				i-=1;
			}//endfor i
		}//endfor ii

		///Reduce ties
		for(int ii=0;ii<part_voice.size();ii+=1){
			bool isInsideTieSegment=false;
			int tieSegStart=-1;
			int tieSegEnd=-1;
			for(int i=0;i<exfmt1ForVoices[ii].evts.size();i+=1){

				if(!isInsideTieSegment){
					if(exfmt1ForVoices[ii].evts[i].tieinfo==0){
						exfmt1.evts.push_back(exfmt1ForVoices[ii].evts[i]);
					}else if(exfmt1ForVoices[ii].evts[i].tieinfo==1){
						isInsideTieSegment=true;
						tieSegStart=i;
						tieSegEnd=-1;
					}else{//Never reach here
						cout<<"Warning: Unexpected tie indication at "<<exfmt1ForVoices[ii].evts[i].stime<<endl;
						exfmt1ForVoices[ii].evts[i].tieinfo=0;
						for(int j=0;j<exfmt1ForVoices[ii].evts[i].numNotes;j+=1){
							exfmt1ForVoices[ii].evts[i].ties[j]=0;
						}//endfor j
						exfmt1.evts.push_back(exfmt1ForVoices[ii].evts[i]);
					}//endif
				}//endif

				/// Tie segmentの切れ目の判定
				if(isInsideTieSegment){//新しくtie segmentが始まったのも含む
					if(i==exfmt1ForVoices[ii].evts.size()-1){
						tieSegEnd=i;
					}else if(exfmt1ForVoices[ii].evts[i+1].tieinfo<2){
						tieSegEnd=i;
					}else{
						bool existsTiedNote=false;
						for(int j=0;j<exfmt1ForVoices[ii].evts[i+1].numNotes;j+=1){
							if(existsTiedNote){break;}
							if(exfmt1ForVoices[ii].evts[i+1].ties[j]==1){
								for(int k=0;k<exfmt1ForVoices[ii].evts[i].numNotes;k+=1){
									if(exfmt1ForVoices[ii].evts[i+1].sitches[j]==exfmt1ForVoices[ii].evts[i].sitches[k]){
										existsTiedNote=true;
										break;
									}//endif
								}//endfor
							}//endif
						}//endfor j
						if(!existsTiedNote){
							tieSegEnd=i;
						}//endif
					}//endif
				}//endif

				if(tieSegEnd>=0){// i でtie segmentが切れる場合

					//tieSegStartからtieSegEndでsubvoice構成
					SubVoiceStructure subVoiceStr;

					vector<int> noteStatus;// size = tieSegEnd-tieSegStart+1
					for(int i_=tieSegStart;i_<=tieSegEnd;i_+=1){
						subVoiceStr.durations.push_back(exfmt1ForVoices[ii].evts[i_].dur);
					}//endfor i_

					for(int i_=tieSegStart;i_<=tieSegEnd;i_+=1){
						for(int j_=0;j_<exfmt1ForVoices[ii].evts[i_].numNotes;j_+=1){
							if(exfmt1ForVoices[ii].evts[i_].ties[j_]==1){continue;}
							noteStatus.assign(tieSegEnd-tieSegStart+1,-1);
							noteStatus[i_-tieSegStart]=0;//Onset
							bool existsTiedPair;
							for(int i__=i_+1;i__<=tieSegEnd;i__+=1){
								existsTiedPair=false;
								for(int j__=0;j__<exfmt1ForVoices[ii].evts[i__].numNotes;j__+=1){
									if(exfmt1ForVoices[ii].evts[i_].sitches[j_]==exfmt1ForVoices[ii].evts[i__].sitches[j__]
									   && exfmt1ForVoices[ii].evts[i__].ties[j__]==1){
										existsTiedPair=true;
										break;
									}//endif
								}//endfor j__
								if(existsTiedPair){
									noteStatus[i__-tieSegStart]=1;
								}else{
									break;
								}//endif
							}//endfor i__

							subVoiceStr.Update(i_,j_,noteStatus);
						}//endfor j_
					}//endfor i_

					ExtendedFmt1xEvt exfmt1evt;
					for(int vv=0;vv<subVoiceStr.subVoices.size();vv+=1){
						for(int t=0;t<subVoiceStr.durations.size();t+=1){
							if(subVoiceStr.subVoices[vv].status[t]!=0){continue;}
							exfmt1evt=exfmt1ForVoices[ii].evts[subVoiceStr.subVoices[vv].poses[t][0][0]];
//							exfmt1evt.stimeはそのままでよいはず
							exfmt1evt.numNotes=0;
							exfmt1evt.sitches.clear();
							exfmt1evt.notetypes.clear();
							exfmt1evt.fmt1IDs.clear();
							exfmt1evt.ties.clear();
							exfmt1evt.subvoice=vv;
							exfmt1evt.dur=subVoiceStr.durations[t];
							for(int t_=t+1;t_<subVoiceStr.durations.size();t_+=1){
								if(subVoiceStr.subVoices[vv].status[t_]!=1){break;}
								exfmt1evt.dur+=subVoiceStr.durations[t_];
							}//endfor t_
							exfmt1evt.tieinfo=0;

							for(int k=0;k<subVoiceStr.subVoices[vv].poses[t].size();k+=1){
								exfmt1evt.numNotes+=1;
								exfmt1evt.sitches.push_back(exfmt1ForVoices[ii].evts[subVoiceStr.subVoices[vv].poses[t][k][0]].sitches[subVoiceStr.subVoices[vv].poses[t][k][1]]);
								exfmt1evt.notetypes.push_back(exfmt1ForVoices[ii].evts[subVoiceStr.subVoices[vv].poses[t][k][0]].notetypes[subVoiceStr.subVoices[vv].poses[t][k][1]]);
								exfmt1evt.fmt1IDs.push_back(exfmt1ForVoices[ii].evts[subVoiceStr.subVoices[vv].poses[t][k][0]].fmt1IDs[subVoiceStr.subVoices[vv].poses[t][k][1]]);
								exfmt1evt.ties.push_back(0);
							}//endfor k
							exfmt1.evts.push_back(exfmt1evt);
						}//endfor t
					}//endfor vv

					isInsideTieSegment=false;
					tieSegStart=-1;
					tieSegEnd=-1;
				}//endif

			}//endfor i
		}//endfor ii

		stable_sort(exfmt1.evts.begin(), exfmt1.evts.end(), LessExtendedFmt1xEvt());

		Fmt3xEvt nevt;
		int curKeyFifth=0;
		int curKeyMode=0;//0=major, 1=minor;

		for(int i=0;i<exfmt1.evts.size();i+=1){
			if(exfmt1.evts[i].eventtype=="attributes"){
				istringstream is(exfmt1.evts[i].info);
				is>>v[1]>>v[2]>>s[3];
				curKeyFifth=v[2];
				curKeyMode=((s[3]=="major")? 0:1);
//	cout<<curKeyFifth<<" "<<curKeyMode<<endl;
				continue;
			}//endif

			ExtendedFmt1xEvt evt=exfmt1.evts[i];
			nevt.stime=evt.stime;
			nevt.barnum=evt.barnum;
			nevt.staff=evt.staff;
			nevt.voice=evt.new_voice;
			nevt.subvoice=evt.subvoice;
			nevt.eventtype=evt.eventtype;
			nevt.dur=evt.dur;
			nevt.sitches.clear(); nevt.notetypes.clear(); nevt.fmt1IDs.clear(); nevt.AFInfo.clear();

			if(nevt.eventtype=="rest"){
			}else if(nevt.eventtype=="chord"){
				for(int j=0;j<evt.numNotes;j+=1){
					nevt.AFInfo.push_back(evt.notetypes[j].substr(evt.notetypes[j].find("."),evt.notetypes[j].size()));
					evt.notetypes[j]=evt.notetypes[j].substr(0,evt.notetypes[j].find("."));
					if(evt.notetypes[j]=="N"){
						nevt.notetypes.push_back("N");
						nevt.sitches.push_back(evt.sitches[j]);
						nevt.fmt1IDs.push_back(evt.fmt1IDs[j]);
					}else{//ornamentation
						nevt.sitches.push_back(evt.sitches[j]
						                       +","+ditchUp(evt.sitches[j],evt.notetypes[j][evt.notetypes[j].size()-2],curKeyFifth)
						                       +","+ditchDown(evt.sitches[j],evt.notetypes[j][evt.notetypes[j].size()-1],curKeyFifth));
						nevt.fmt1IDs.push_back(evt.fmt1IDs[j]);
						if(evt.notetypes[j].find("trill-mark")!=string::npos){ss<<"Tr\t";nevt.notetypes.push_back("Tr");
						}else if(evt.notetypes[j].find("inverted-mordent")!=string::npos){ss<<"Im\t";nevt.notetypes.push_back("Im");
						}else if(evt.notetypes[j].find("mordent")!=string::npos){ss<<"Mr\t";nevt.notetypes.push_back("Mr");
						}else if(evt.notetypes[j].find("delayed-inverted-turn")!=string::npos){ss<<"DIt\t";nevt.notetypes.push_back("DIt");
						}else if(evt.notetypes[j].find("delayed-turn")!=string::npos){ss<<"Dt\t";nevt.notetypes.push_back("Dt");
						}else if(evt.notetypes[j].find("inverted-turn")!=string::npos){ss<<"It\t";nevt.notetypes.push_back("It");
						}else if(evt.notetypes[j].find("turn")!=string::npos){ss<<"Tn\t";nevt.notetypes.push_back("Tn");
						}else{
							cout<<"Unknown ornament type! : "<<evt.notetypes[j]<<endl;
							assert(false);
						}//endif
					}//endif
				}//endfor j
				assert(evt.numNotes==nevt.notetypes.size());
			}else if(evt.eventtype=="tremolo-s"){
				nevt.dur=0;
				nevt.eventtype="tremolo";
				int reset_i=i;
				while(true){
					if(exfmt1.evts[i].eventtype.find("tremolo")==string::npos){
						i+=1;
						continue;
					}//endif
					nevt.dur+=exfmt1.evts[i].dur;
					ss.str("");
					for(int j=0;j<exfmt1.evts[i].numNotes;j+=1){
						ss<<exfmt1.evts[i].sitches[j];
						if(j<exfmt1.evts[i].numNotes-1){ss<<",";}
					}//endfor j
					nevt.sitches.push_back(ss.str());
					ss.str(""); ss<<exfmt1.evts[i].numNotes;
					nevt.notetypes.push_back(ss.str());
					ss.str("");
					for(int j=0;j<exfmt1.evts[i].numNotes;j+=1){
						ss<<exfmt1.evts[i].fmt1IDs[j];
						if(j<exfmt1.evts[i].numNotes-1){ss<<",";}
					}//endfor j
					nevt.fmt1IDs.push_back(ss.str());
					nevt.AFInfo.push_back("");
					if(exfmt1.evts[i].eventtype=="tremolo-e"){break;};
					i+=1;
				}//endwhile
				evts.push_back(nevt);
				i=reset_i;
				continue;
			}else{//tremolo-eなど
				continue;
			}//endif

			if(nevt.dur==0){nevt.eventtype="short-app";}//後でafter-noteかどうかを判定
			evts.push_back(nevt);

		}//endfor i

		//// Eliminate redundancies and sort nevtSeq, extract after-notes after trills
{
		vector<vector<Fmt3xEvt> > voice_nevtSeq(part_voice.size());
		for(int i=0;i<evts.size();i+=1){
			voice_nevtSeq[evts[i].voice].push_back(evts[i]);
		}//endfor i

		/// Reduce rests and tremolos and convert short-app after trills to after-notes
		for(int i=0;i<part_voice.size();i+=1){

			bool after_trill=false;
			if(voice_nevtSeq[i][0].eventtype=="chord"){
				for(int k=0;k<voice_nevtSeq[i][0].notetypes.size();k+=1){
					if(voice_nevtSeq[i][0].notetypes[k].find("Tr")!=string::npos){after_trill=true; break;}
				}//endfor k
			}//endif

			for(int j=1;j<voice_nevtSeq[i].size();j+=1){
				if(voice_nevtSeq[i][j].eventtype=="chord"||voice_nevtSeq[i][j].eventtype=="rest"){
					after_trill=false;
				}//endif

				if(voice_nevtSeq[i][j].eventtype=="chord"){
					for(int k=0;k<voice_nevtSeq[i][j].notetypes.size();k+=1){
						if(voice_nevtSeq[i][j].notetypes[k].find("Tr")!=string::npos){after_trill=true; break;}
					}//endfor k
				}else if(after_trill&&voice_nevtSeq[i][j].eventtype=="short-app"){
					voice_nevtSeq[i][j].eventtype="after-note";
				}else if(voice_nevtSeq[i][j-1].eventtype=="rest"&&voice_nevtSeq[i][j].eventtype=="rest"){
					voice_nevtSeq[i][j-1].dur+=voice_nevtSeq[i][j].dur;
					voice_nevtSeq[i].erase(voice_nevtSeq[i].begin()+j);
					j-=1;
				}else if(voice_nevtSeq[i][j-1].eventtype=="tremolo"&&voice_nevtSeq[i][j].eventtype=="tremolo"
					&&voice_nevtSeq[i][j-1].sitches==voice_nevtSeq[i][j].sitches
					&&voice_nevtSeq[i][j-1].notetypes==voice_nevtSeq[i][j].notetypes){
					voice_nevtSeq[i][j-1].dur+=voice_nevtSeq[i][j].dur;
					voice_nevtSeq[i].erase(voice_nevtSeq[i].begin()+j);
					j-=1;
				}//endif
			}//endfor j

			/// Set subOrder
			long prev_stime=voice_nevtSeq[i][0].stime;
			int subcount=1, afterNoteCount=0;
			voice_nevtSeq[i][0].subOrder=0;
			for(int j=1;j<voice_nevtSeq[i].size();j+=1){
				if(voice_nevtSeq[i][j].stime==prev_stime && voice_nevtSeq[i][j-1].dur==0){
					voice_nevtSeq[i][j].subOrder=voice_nevtSeq[i][j-1].subOrder+1;
				}else if(voice_nevtSeq[i][j].stime==prev_stime){
					voice_nevtSeq[i][j].subOrder=voice_nevtSeq[i][j-1].subOrder;
				}else{
					for(int k=0;k<subcount;k+=1){
						voice_nevtSeq[i][j-1-k].subOrder-=afterNoteCount;
					}//endfor k
					prev_stime=voice_nevtSeq[i][j].stime;
					voice_nevtSeq[i][j].subOrder=0;
					subcount=0;
					afterNoteCount=0;
				}//endif
				subcount+=1;
				if(voice_nevtSeq[i][j].eventtype=="after-note"){
					afterNoteCount+=1;
				}//endif
			}//endfor j
			for(int k=0;k<subcount;k+=1){
				voice_nevtSeq[i][voice_nevtSeq[i].size()-1-k].subOrder-=afterNoteCount;
			}//endfor k

		}//endfor i

		/// Merge and sort
		evts.clear();
		for(int i=0;i<part_voice.size();i+=1){
			for(int j=0;j<voice_nevtSeq[i].size();j+=1){
				evts.push_back(voice_nevtSeq[i][j]);
			}//endfor j
		}//endfor i
		stable_sort(evts.begin(), evts.end(), LessFmt3xEvt());

}//

		/// Set numNotes and notetypes
		for(int i=0;i<evts.size();i+=1){
			evts[i].numNotes=evts[i].notetypes.size();
			for(int j=0;j<evts[i].numNotes;j+=1){
				evts[i].notetypes[j]=evts[i].notetypes[j]+evts[i].AFInfo[j];
			}//endfor j
		}//endfor i

		/// Find duplicate onsets
{
		DuplicateOnsetEvtInFmt3x dup;
		vector<vector<vector<int> > > indecesPerPitch;//indecesPerPitch[p][k][0,1]=i,j for evts[i].sitches[j]
		vector<int> vi(2);
		vector<string> uniqueFmt1IDs;
		indecesPerPitch.clear();
		indecesPerPitch.resize(128);
		if(evts[0].eventtype=="chord"){
			for(int j=0;j<evts[0].numNotes;j+=1){
				vi[0]=0; vi[1]=j;
				indecesPerPitch[SitchToPitch(evts[0].sitches[j].substr(0,evts[0].sitches[j].find(",")))].push_back(vi);
			}//endfor j
		}//endif
		for(int i=1;i<evts.size();i+=1){

			if(evts[i].stime!=evts[i-1].stime){
				for(int p=0;p<128;p+=1){
					if(indecesPerPitch[p].size()>1){
						dup.stime=evts[indecesPerPitch[p][0][0]].stime;
						dup.sitch=evts[indecesPerPitch[p][0][0]].sitches[indecesPerPitch[p][0][1]];
						dup.fmt1IDs.clear();
						for(int k=indecesPerPitch[p].size()-1;k>=0;k-=1){
							dup.fmt1IDs.push_back(evts[indecesPerPitch[p][k][0]].fmt1IDs[indecesPerPitch[p][k][1]]);
						}//endfor k
						dup.numOnsets=dup.fmt1IDs.size();
						duplicateOnsets.push_back(dup);
					}//endif
				}//endfor p
				indecesPerPitch.clear();
				indecesPerPitch.resize(128);
			}//endif

			if(evts[i].eventtype!="chord"){continue;}

			for(int j=0;j<evts[i].numNotes;j+=1){
				vi[0]=i; vi[1]=j;
				indecesPerPitch[SitchToPitch(evts[i].sitches[j].substr(0,evts[i].sitches[j].find(",")))].push_back(vi);
			}//endfor j

		}//endfor i

		for(int p=0;p<128;p+=1){
			if(indecesPerPitch[p].size()>1){
				dup.stime=evts[indecesPerPitch[p][0][0]].stime;
				dup.sitch=evts[indecesPerPitch[p][0][0]].sitches[indecesPerPitch[p][0][1]];
				dup.fmt1IDs.clear();
				for(int k=indecesPerPitch[p].size()-1;k>=0;k-=1){
					dup.fmt1IDs.push_back(evts[indecesPerPitch[p][k][0]].fmt1IDs[indecesPerPitch[p][k][1]]);
				}//endfor k
				dup.numOnsets=dup.fmt1IDs.size();
				duplicateOnsets.push_back(dup);
			}//endif
		}//endfor p

}//

	}//end ConvertFromFmt1x

	void ConvertFromPianoRoll(PianoRoll pr){

		stringstream ss;
		vector<vector<int> > clusters;
		double thres=0.035;//35 ms for chord clustering

{
		vector<int> vi;
		vi.push_back(0);
		for(int n=1;n<pr.evts.size();n+=1){
			if(pr.evts[n].ontime-pr.evts[n-1].ontime>thres){
				clusters.push_back(vi);
				vi.clear();
			}//endif
			vi.push_back(n);
		}//endfor n
		clusters.push_back(vi);
}//

		Clear();
		TPQN=1000;// 1 tick <-> 1 ms

{
		Fmt3xEvt evt;
		evt.barnum="1";
		evt.staff=0;
		evt.voice=0;
		evt.subvoice=0;
		evt.subOrder=0;
		evt.eventtype="chord";
		vector<string> vs;
		vector<vector<string> > fmt1IDsPerPitch;

		for(int i=0;i<clusters.size();i+=1){

			fmt1IDsPerPitch.assign(128,vs);

			double clusterOntime=0;
			for(int j=0;j<clusters[i].size();j+=1){
				clusterOntime+=pr.evts[clusters[i][j]].ontime;
			}//endfor j
			clusterOntime/=double(clusters[i].size());
			evt.stime=int(1000*clusterOntime);

			evt.sitches.clear();
			evt.notetypes.clear();
			evt.fmt1IDs.clear();
			for(int j=0;j<clusters[i].size();j+=1){
				evt.sitches.push_back(pr.evts[clusters[i][j]].sitch);
				evt.notetypes.push_back("N..");
				ss.str("");
				ss<<"P1-1-"<<clusters[i][j];
				evt.fmt1IDs.push_back(ss.str());
				fmt1IDsPerPitch[SitchToPitch(pr.evts[clusters[i][j]].sitch)].push_back(ss.str());
			}//endfor j
			evt.numNotes=evt.sitches.size();

			evts.push_back(evt);

			for(int k=0;k<128;k+=1){
				if(fmt1IDsPerPitch[k].size()>1){
					DuplicateOnsetEvtInFmt3x dup;
					dup.stime=evt.stime;
					dup.sitch=PitchToSitch(k);
					dup.numOnsets=fmt1IDsPerPitch[k].size();
					dup.fmt1IDs=fmt1IDsPerPitch[k];
				}//endif
			}//endfor k

		}//endfor i

		///Set dur
		for(int i=1;i<evts.size();i+=1){
			evts[i-1].dur=evts[i].stime-evts[i-1].stime;
		}//endfor i
		evts[evts.size()-1].dur=TPQN;

}//

	}//end ConvertFromPianoRoll




};//endclass Fmt3x

#endif // FMT3X_HPP
