#ifndef FMT2_HPP
#define FMT2_HPP

#include<iostream>
#include<fstream>
#include<string>
#include<sstream>
#include<vector>
#include<stdio.h>
#include<cmath>
#include<cassert>
//#include"Fmt1_v170101.hpp"
#include"Fmt1x_v170108_2.hpp"

using namespace std;

class Fmt2Evt{
public:
	int stime;
	int voice;
	string eventtype;
	int dur;
	int numNotes;
	vector<string> sitches;//sitch content
	vector<string> notetypes;//N or Tr etc.
	vector<string> fmt1IDs;//id in fmt1
	vector<string> AFInfo;//information on arpeggio and fermata
};//endclass Fmt2Evt

class LessFmt2EvtStime{
public:
	bool operator()(const Fmt2Evt& a, const Fmt2Evt& b){ return a.stime < b.stime;}
};
//stable_sort(fmt2EvtSeq.begin(), fmt2EvtSeq.end(), LessFmt2EvtStime());

class Fmt2{
public:
	vector<string> comments;
	vector<Fmt2Evt> evts;
	int TPQN;

	void ReadFile(string filename){
		comments.clear();
		evts.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;

		Fmt2Evt evt;
		ifstream ifs(filename.c_str());
		if(!ifs.is_open()){cout<<"File not found: "<<filename<<endl; assert(false);}
		while(ifs>>s[0]){
			if(s[0][0]=='/' || s[0][0]=='#'){
				if(s[0]=="//TPQN:"){
					ifs>>TPQN;
					getline(ifs,s[99]);
				}else if(s[0]=="//Fmt2Version:"){
					ifs>>s[1];
					if(s[1]!="170101"){
						cout<<"Warning: The fmt2 version is not 170101!"<<endl;
					}//endif
					getline(ifs,s[99]);
				}else{
					getline(ifs,s[99]);
					comments.push_back(s[99]);
				}//endif
				continue;
			}//endif
			evt.stime=atoi(s[0].c_str());
			ifs>>evt.voice>>evt.eventtype>>evt.dur>>evt.numNotes;
			evt.fmt1IDs.clear(); evt.sitches.clear(); evt.notetypes.clear();
			for(int j=0;j<evt.numNotes;j+=1){ifs>>s[10]; evt.notetypes.push_back(s[10]);}//endfor j
			for(int j=0;j<evt.numNotes;j+=1){ifs>>s[10]; evt.sitches.push_back(s[10]);}//endfor j
			for(int j=0;j<evt.numNotes;j+=1){ifs>>s[10]; evt.fmt1IDs.push_back(s[10]);}//endfor j
			getline(ifs,s[99]);
			evts.push_back(evt);
		}//endwhile
		ifs.close();
	}//end ReadFile

	void WriteFile(string filename){
		ofstream ofs(filename.c_str());
		ofs<<"//TPQN: "<<TPQN<<"\n";
		ofs<<"//Fmt2Version: 170101\n";
		for(int i=0;i<comments.size();i+=1){
			ofs<<"// "<<comments[i];
		}//endfor i
		for(int i=0;i<evts.size();i+=1){
			ofs<<evts[i].stime<<"\t"<<evts[i].voice<<"\t"<<evts[i].eventtype<<"\t"<<evts[i].dur<<"\t"<<evts[i].numNotes<<"\t";
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].notetypes[j]<<"\t";}//endfor j
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].sitches[j]<<"\t";}//endfor j
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].fmt1IDs[j]<<"\t";}//endfor j
			ofs<<"\n";
		}//endfor i
		ofs.close();
	}//end WriteFile

	Fmt2Evt Assign(Fmt2Evt evt_,string notetype,string sitch,string fmt1ID){
		Fmt2Evt evt;
		evt=evt_;
		evt.notetypes.clear(); evt.sitches.clear(); evt.fmt1IDs.clear();
		evt.notetypes.push_back(notetype);
		evt.sitches.push_back(sitch);
		evt.fmt1IDs.push_back(fmt1ID);
		return evt;
	}//end Assign

/*
	void ConvertFromFmt1(Fmt1 fmt1){
		comments.clear();
		evts.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		TPQN=fmt1.TPQN;

		vector<vector<int> > part_voice;
{
		vector<int> vi(2);
		for(int i=0;i<fmt1.evts.size();i+=1){
			vi[0]=fmt1.evts[i].part;
			vi[1]=fmt1.evts[i].voice;
			if(part_voice.size()==0 || find(part_voice.begin(),part_voice.end(),vi)==part_voice.end()){
				part_voice.push_back(vi);
			}//endif
		}//endfor i
}//
//cout<<"part_voice.size() : "<<part_voice.size()<<endl;

{
		vector<int> lastPositionPerVoice(part_voice.size());
		Fmt2Evt nevt;
		vector<int> vi(2);
		string curInfo;
		int curKeyFifth=0;
		int curKeyMode=0;//0=major, 1=minor;

		vector<string> tmp_pitch,tmp_type;
		stringstream tmp_pitch_info;
		for(int i=0;i<fmt1.evts.size();i+=1){
			if(fmt1.evts[i].eventtype=="attributes"){
				istringstream is(fmt1.evts[i].info);
				is>>v[1]>>v[2]>>s[3];
				curKeyFifth=v[2];
				curKeyMode=((s[3]=="major")? 0:1);
	//cout<<curKeyFifth<<" "<<curKeyMode<<endl;
				continue;
			}//endif
			vi[0]=fmt1.evts[i].part;
			vi[1]=fmt1.evts[i].voice;
			nevt.voice=find(part_voice.begin(),part_voice.end(),vi)-part_voice.begin();
			nevt.stime=fmt1.evts[i].stime;
			nevt.eventtype=fmt1.evts[i].eventtype;
			nevt.dur=fmt1.evts[i].dur;

			v[3]=fmt1.evts[i].numNotes;
			nevt.notetypes.clear();
			nevt.AFInfo.clear();
			nevt.sitches.clear();
			nevt.fmt1IDs.clear();
			if(nevt.eventtype=="rest"){
				curInfo="";
			}else if(nevt.eventtype=="chord"){
				tmp_pitch=fmt1.evts[i].sitches;
				tmp_type=fmt1.evts[i].notetypes;
				tmp_pitch_info.str("");

				for(int j=0;j<fmt1.evts[i].numNotes;j+=1){
					nevt.AFInfo.push_back(tmp_type[j].substr(tmp_type[j].find("."),tmp_type[j].size()));
					tmp_type[j]=tmp_type[j].substr(0,tmp_type[j].find("."));
					if(tmp_type[j].substr(0,tmp_type[j].find("."))=="N"){
						nevt.notetypes.push_back("N");
						nevt.sitches.push_back(tmp_pitch[j]);
						ss.str(""); ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
						nevt.fmt1IDs.push_back(ss.str());
						ss<<"N\t";
						tmp_pitch_info<<tmp_pitch[j]<<"\t";
					}else{
						tmp_pitch_info<<tmp_pitch[j]<<",";
						tmp_pitch_info<<ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth)<<",";
						tmp_pitch_info<<ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth)<<"\t";
						nevt.sitches.push_back(tmp_pitch[j]+","+ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth)+","+
											ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth));
						ss.str(""); ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
						nevt.fmt1IDs.push_back(ss.str());
						if(tmp_type[j].find("trill-mark")!=string::npos){ss<<"Tr\t";nevt.notetypes.push_back("Tr");
						}else if(tmp_type[j].find("inverted-mordent")!=string::npos){ss<<"Im\t";nevt.notetypes.push_back("Im");
						}else if(tmp_type[j].find("mordent")!=string::npos){ss<<"Mr\t";nevt.notetypes.push_back("Mr");
						}else if(tmp_type[j].find("delayed-inverted-turn")!=string::npos){ss<<"DIt\t";nevt.notetypes.push_back("DIt");
						}else if(tmp_type[j].find("delayed-turn")!=string::npos){ss<<"Dt\t";nevt.notetypes.push_back("Dt");
						}else if(tmp_type[j].find("inverted-turn")!=string::npos){ss<<"It\t";nevt.notetypes.push_back("It");
						}else if(tmp_type[j].find("turn")!=string::npos){ss<<"Tn\t";nevt.notetypes.push_back("Tn");
						}else{
							cout<<"Unknown ornament type! : "<<tmp_type[j]<<endl;
							assert(false);
						}//endif
					}//endif
				}//endfor j
				ss<<tmp_pitch_info.str();
				curInfo=ss.str();
			}else if(fmt1.evts[i].eventtype=="tremolo-s"){
				nevt.dur=0;
				nevt.eventtype="tremolo";
				while(true){
					nevt.dur+=fmt1.evts[i].dur;
					ss.str("");
					for(int j=0;j<fmt1.evts[i].numNotes;j+=1){
						ss<<fmt1.evts[i].sitches[j];
						if(j<fmt1.evts[i].numNotes-1){ss<<",";}
					}//endfor j
					nevt.sitches.push_back(ss.str());
					ss.str(""); ss<<fmt1.evts[i].numNotes;
					nevt.notetypes.push_back(ss.str());
					ss.str("");
					for(int j=0;j<fmt1.evts[i].numNotes;j+=1){
						ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
						if(j<fmt1.evts[i].numNotes-1){ss<<",";}
					}//endfor j
					nevt.fmt1IDs.push_back(ss.str());
					nevt.AFInfo.push_back("");
					if(fmt1.evts[i].eventtype=="tremolo-e"){break;};
					i+=1;
				}//endwhile
				evts.push_back(nevt);
				continue;
			}//endif

			if(fmt1.evts[i].tieinfo>=2){
				if(nevt.eventtype!=evts[lastPositionPerVoice[nevt.voice]].eventtype){
	//cout<<"//Warning: tie between different event types! at "<<i<<endl;
				continue;
				}//endif
				evts[lastPositionPerVoice[nevt.voice]].dur+=nevt.dur;
				continue;
			}//endif
			if(nevt.dur==0){nevt.eventtype="short-app";}

			for(int j=0;j<nevt.notetypes.size();j+=1){
				if(nevt.notetypes[j]=="Im"){
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.dur=0;
					tnevt.eventtype="short-app";
					ss.str(""); ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					nevt.notetypes[j]="N";
					nevt.sitches[j]=tmp_pitch[j];
					tnevt.fmt1IDs[j]=ss.str();
				}else if(nevt.notetypes[j]=="Mr"){
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.dur=0;
					tnevt.eventtype="short-app";
					ss.str(""); ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					nevt.notetypes[j]="N";
					nevt.sitches[j]=tmp_pitch[j];
					tnevt.fmt1IDs[j]=ss.str();
				}else if(nevt.notetypes[j]=="Tn"){
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.dur=0;
					tnevt.eventtype="short-app";
					ss.str(""); ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					nevt.notetypes[j]="N";
					nevt.sitches[j]=tmp_pitch[j];
					tnevt.fmt1IDs[j]=ss.str();
				}else if(nevt.notetypes[j]=="It"){
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.dur=0;
					tnevt.eventtype="short-app";
					ss.str(""); ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					nevt.notetypes[j]="N";
					nevt.sitches[j]=tmp_pitch[j];
					tnevt.fmt1IDs[j]=ss.str();
				}//endif
			}//endfor j

			evts.push_back(nevt);
			for(int j=0;j<nevt.notetypes.size();j+=1){
				if(nevt.notetypes[j]=="Dt"){
					evts[evts.size()-1].notetypes[j]="N";
					evts[evts.size()-1].sitches[j]=tmp_pitch[j];
					ss.str(""); ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
					evts[evts.size()-1].fmt1IDs[j]=ss.str();
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.stime+=nevt.dur;
					tnevt.dur=0;
					tnevt.eventtype="after-note";
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
				}else if(nevt.notetypes[j]=="IDt"){
					evts[evts.size()-1].notetypes[j]="N";
					evts[evts.size()-1].sitches[j]=tmp_pitch[j];
					ss.str(""); ss<<"P"<<fmt1.evts[i].part<<"-"<<fmt1.evts[i].barnum<<"-"<<fmt1.evts[i].notenums[j];
					evts[evts.size()-1].fmt1IDs[j]=ss.str();
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.stime+=nevt.dur;
					tnevt.dur=0;
					tnevt.eventtype="after-note";
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
				}//endif
			}//endfor j
			lastPositionPerVoice[nevt.voice]=evts.size()-1;
		}//endfor i
}//

//// Eliminate redundancies and sort nevtSeq, extract after-notes after trills
{
		int prevNum=evts.size();
		int NumOfVoices=part_voice.size();
		vector<vector<Fmt2Evt> > voice_nevtSeq(NumOfVoices);
		int largestStime=0;
		for(int i=0;i<evts.size();i+=1){
			voice_nevtSeq[evts[i].voice].push_back(evts[i]);
			if(evts[i].stime>largestStime){largestStime=evts[i].stime;}
		}//endfor i

		/// reducing rests and tremolos
		/// converting short-app after trills to after-notes
		for(int i=0;i<NumOfVoices;i+=1){
			bool after_trill=false;
			if(voice_nevtSeq[i][0].eventtype=="chord"){
				for(int k=0;k<voice_nevtSeq[i][0].notetypes.size();k+=1){
					if(voice_nevtSeq[i][0].notetypes[k].find("Tr")!=string::npos){
						after_trill=true;
						break;
					}//endif
				}//endfor k
			}//endif
			for(int j=1;j<voice_nevtSeq[i].size();j+=1){
				if(voice_nevtSeq[i][j].eventtype=="chord"||voice_nevtSeq[i][j].eventtype=="rest"){
					after_trill=false;
				}//endif
				if(voice_nevtSeq[i][j].eventtype=="chord"){
					for(int k=0;k<voice_nevtSeq[i][j].notetypes.size();k+=1){
						if(voice_nevtSeq[i][j].notetypes[k].find("Tr")!=string::npos){
							after_trill=true;
							break;
						}//endif
					}//endfor k
				}//endif
				if(after_trill&&voice_nevtSeq[i][j].eventtype=="short-app"){
					voice_nevtSeq[i][j].eventtype="after-note";
				}//endif
				if(voice_nevtSeq[i][j-1].eventtype=="rest"&&voice_nevtSeq[i][j].eventtype=="rest"){
					voice_nevtSeq[i][j-1].dur+=voice_nevtSeq[i][j].dur;
					voice_nevtSeq[i].erase(voice_nevtSeq[i].begin()+j);
					j-=1;
				}//endif
				if(voice_nevtSeq[i][j-1].eventtype=="tremolo"&&voice_nevtSeq[i][j].eventtype=="tremolo"
					&&voice_nevtSeq[i][j-1].sitches==voice_nevtSeq[i][j].sitches
					&&voice_nevtSeq[i][j-1].notetypes==voice_nevtSeq[i][j].notetypes){
					voice_nevtSeq[i][j-1].dur+=voice_nevtSeq[i][j].dur;
					voice_nevtSeq[i].erase(voice_nevtSeq[i].begin()+j);
					j-=1;
				}//endif
			}//endfor j
		}//endfor i

		/// Sorting nevtSeq
		int curstime=evts[0].stime;
		vector<int> numPerVoice(NumOfVoices);
		vector<int> posPerVoice(NumOfVoices);
		for(int i=0;i<NumOfVoices;i+=1){
			numPerVoice[i]=voice_nevtSeq[i].size();
			posPerVoice[i]=0;
		}//endfor i
		evts.clear();
		bool ended=false;
		bool found;
		while(!ended){
			found=false;
			for(int i=0;i<NumOfVoices;i+=1){
				if(posPerVoice[i]<=numPerVoice[i]-1 && curstime==voice_nevtSeq[i][posPerVoice[i]].stime){
					evts.push_back(voice_nevtSeq[i][posPerVoice[i]]);
					posPerVoice[i]+=1;
					found=true;
					break;
				}//endif
			}//endfor i
			if(found){
				ended=true;
				for(int i=0;i<NumOfVoices;i+=1){
					if(posPerVoice[i]<=numPerVoice[i]-1){ended=false; break;}
				}//endfor i
			}else{
				curstime=largestStime+1;
				for(int i=0;i<NumOfVoices;i+=1){
					if(posPerVoice[i]>numPerVoice[i]-1){continue;}
					if(voice_nevtSeq[i][posPerVoice[i]].stime<curstime){curstime=voice_nevtSeq[i][posPerVoice[i]].stime;}
				}//endfor i
			}//endif
		}//endwhile
	//	assert(nevtSeq.size()==prevNum);//for cheking!
}//

		for(int i=0;i<evts.size();i+=1){
			evts[i].numNotes=evts[i].sitches.size();
			for(int j=0;j<evts[i].numNotes;j+=1){
				evts[i].notetypes[j]=evts[i].notetypes[j]+evts[i].AFInfo[j];
			}//endfor j
		}//endfor i

	}//end ConvertFromFmt1
*/


	void ConvertFromFmt1x(Fmt1x fmt1){
		comments.clear();
		evts.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		TPQN=fmt1.TPQN;

		vector<vector<int> > part_voice;
{
		vector<int> vi(2);
		for(int i=0;i<fmt1.evts.size();i+=1){
			vi[0]=fmt1.evts[i].part;
			vi[1]=fmt1.evts[i].voice;
			if(part_voice.size()==0 || find(part_voice.begin(),part_voice.end(),vi)==part_voice.end()){
				part_voice.push_back(vi);
			}//endif
		}//endfor i
}//
//cout<<"part_voice.size() : "<<part_voice.size()<<endl;

		/// Break partial ties
		for(int i=0;i<fmt1.evts.size();i+=1){
			if(fmt1.evts[i].tieinfo<2){continue;}
			bool isPartialTie=false;
			for(int j=0;j<fmt1.evts[i].ties.size();j+=1){
				if(fmt1.evts[i].ties[j]==0){isPartialTie=true; break;}
			}//endfor j
			if(isPartialTie){
				fmt1.evts[i].tieinfo-=2;
			}//endif
		}//endfor i

{
		vector<int> lastPositionPerVoice(part_voice.size());
		Fmt2Evt nevt;
		vector<int> vi(2);
		string curInfo;
		int curKeyFifth=0;
		int curKeyMode=0;//0=major, 1=minor;

		vector<string> tmp_pitch,tmp_type;
		stringstream tmp_pitch_info;
		for(int i=0;i<fmt1.evts.size();i+=1){
			if(fmt1.evts[i].eventtype=="attributes"){
				istringstream is(fmt1.evts[i].info);
				is>>v[1]>>v[2]>>s[3];
				curKeyFifth=v[2];
				curKeyMode=((s[3]=="major")? 0:1);
	//cout<<curKeyFifth<<" "<<curKeyMode<<endl;
				continue;
			}//endif
			vi[0]=fmt1.evts[i].part;
			vi[1]=fmt1.evts[i].voice;
			nevt.voice=find(part_voice.begin(),part_voice.end(),vi)-part_voice.begin();
			nevt.stime=fmt1.evts[i].stime;
			nevt.eventtype=fmt1.evts[i].eventtype;
			nevt.dur=fmt1.evts[i].dur;

			v[3]=fmt1.evts[i].numNotes;
			nevt.notetypes.clear();
			nevt.AFInfo.clear();
			nevt.sitches.clear();
			nevt.fmt1IDs.clear();
			if(nevt.eventtype=="rest"){
				curInfo="";
			}else if(nevt.eventtype=="chord"){
				tmp_pitch=fmt1.evts[i].sitches;
				tmp_type=fmt1.evts[i].notetypes;
				tmp_pitch_info.str("");

				for(int j=0;j<fmt1.evts[i].numNotes;j+=1){
					nevt.AFInfo.push_back(tmp_type[j].substr(tmp_type[j].find("."),tmp_type[j].size()));
					tmp_type[j]=tmp_type[j].substr(0,tmp_type[j].find("."));
					if(tmp_type[j].substr(0,tmp_type[j].find("."))=="N"){
						nevt.notetypes.push_back("N");
						nevt.sitches.push_back(tmp_pitch[j]);
						ss.str(""); ss<<fmt1.evts[i].fmt1IDs[j];
						nevt.fmt1IDs.push_back(ss.str());
						ss<<"N\t";
						tmp_pitch_info<<tmp_pitch[j]<<"\t";
					}else{
						tmp_pitch_info<<tmp_pitch[j]<<",";
						tmp_pitch_info<<ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth)<<",";
						tmp_pitch_info<<ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth)<<"\t";
						nevt.sitches.push_back(tmp_pitch[j]+","+ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth)+","+
											ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth));
						ss.str(""); ss<<fmt1.evts[i].fmt1IDs[j];
						nevt.fmt1IDs.push_back(ss.str());
						if(tmp_type[j].find("trill-mark")!=string::npos){ss<<"Tr\t";nevt.notetypes.push_back("Tr");
						}else if(tmp_type[j].find("inverted-mordent")!=string::npos){ss<<"Im\t";nevt.notetypes.push_back("Im");
						}else if(tmp_type[j].find("mordent")!=string::npos){ss<<"Mr\t";nevt.notetypes.push_back("Mr");
						}else if(tmp_type[j].find("delayed-inverted-turn")!=string::npos){ss<<"DIt\t";nevt.notetypes.push_back("DIt");
						}else if(tmp_type[j].find("delayed-turn")!=string::npos){ss<<"Dt\t";nevt.notetypes.push_back("Dt");
						}else if(tmp_type[j].find("inverted-turn")!=string::npos){ss<<"It\t";nevt.notetypes.push_back("It");
						}else if(tmp_type[j].find("turn")!=string::npos){ss<<"Tn\t";nevt.notetypes.push_back("Tn");
						}else{
							cerr<<"Unknown ornament type! : "<<tmp_type[j]<<endl;//->treated as a trill
							ss<<"Tr\t";nevt.notetypes.push_back("Tr");
						}//endif
					}//endif
				}//endfor j
				ss<<tmp_pitch_info.str();
				curInfo=ss.str();
			}else if(fmt1.evts[i].eventtype=="tremolo-s"){
				nevt.dur=0;
				nevt.eventtype="tremolo";
				while(true){
					nevt.dur+=fmt1.evts[i].dur;
					ss.str("");
					for(int j=0;j<fmt1.evts[i].numNotes;j+=1){
						ss<<fmt1.evts[i].sitches[j];
						if(j<fmt1.evts[i].numNotes-1){ss<<",";}
					}//endfor j
					nevt.sitches.push_back(ss.str());
					ss.str(""); ss<<fmt1.evts[i].numNotes;
					nevt.notetypes.push_back(ss.str());
					ss.str("");
					for(int j=0;j<fmt1.evts[i].numNotes;j+=1){
						ss<<fmt1.evts[i].fmt1IDs[j];
						if(j<fmt1.evts[i].numNotes-1){ss<<",";}
					}//endfor j
					nevt.fmt1IDs.push_back(ss.str());
					nevt.AFInfo.push_back("");
					if(fmt1.evts[i].eventtype=="tremolo-e"){break;};
					i+=1;
				}//endwhile
				evts.push_back(nevt);
				continue;
			}//endif

			if(fmt1.evts[i].tieinfo>=2){
				if(nevt.eventtype!=evts[lastPositionPerVoice[nevt.voice]].eventtype){
	//cout<<"//Warning: tie between different event types! at "<<i<<endl;
				continue;
				}//endif
				evts[lastPositionPerVoice[nevt.voice]].dur+=nevt.dur;
				continue;
			}//endif
			if(nevt.dur==0){nevt.eventtype="short-app";}

			for(int j=0;j<nevt.notetypes.size();j+=1){
				if(nevt.notetypes[j]=="Im"){
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.dur=0;
					tnevt.eventtype="short-app";
					ss.str(""); ss<<fmt1.evts[i].fmt1IDs[j];
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					nevt.notetypes[j]="N";
					nevt.sitches[j]=tmp_pitch[j];
					tnevt.fmt1IDs[j]=ss.str();
				}else if(nevt.notetypes[j]=="Mr"){
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.dur=0;
					tnevt.eventtype="short-app";
					ss.str(""); ss<<fmt1.evts[i].fmt1IDs[j];
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					nevt.notetypes[j]="N";
					nevt.sitches[j]=tmp_pitch[j];
					tnevt.fmt1IDs[j]=ss.str();
				}else if(nevt.notetypes[j]=="Tn"){
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.dur=0;
					tnevt.eventtype="short-app";
					ss.str(""); ss<<fmt1.evts[i].fmt1IDs[j];
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					nevt.notetypes[j]="N";
					nevt.sitches[j]=tmp_pitch[j];
					tnevt.fmt1IDs[j]=ss.str();
				}else if(nevt.notetypes[j]=="It"){
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.dur=0;
					tnevt.eventtype="short-app";
					ss.str(""); ss<<fmt1.evts[i].fmt1IDs[j];
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					nevt.notetypes[j]="N";
					nevt.sitches[j]=tmp_pitch[j];
					tnevt.fmt1IDs[j]=ss.str();
				}//endif
			}//endfor j

			evts.push_back(nevt);
			for(int j=0;j<nevt.notetypes.size();j+=1){
				if(nevt.notetypes[j]=="Dt"){
					evts[evts.size()-1].notetypes[j]="N";
					evts[evts.size()-1].sitches[j]=tmp_pitch[j];
					ss.str(""); ss<<fmt1.evts[i].fmt1IDs[j];
					evts[evts.size()-1].fmt1IDs[j]=ss.str();
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.stime+=nevt.dur;
					tnevt.dur=0;
					tnevt.eventtype="after-note";
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
				}else if(nevt.notetypes[j]=="IDt"){
					evts[evts.size()-1].notetypes[j]="N";
					evts[evts.size()-1].sitches[j]=tmp_pitch[j];
					ss.str(""); ss<<fmt1.evts[i].fmt1IDs[j];
					evts[evts.size()-1].fmt1IDs[j]=ss.str();
					Fmt2Evt tnevt;
					tnevt=nevt;
					tnevt.stime+=nevt.dur;
					tnevt.dur=0;
					tnevt.eventtype="after-note";
					tnevt=Assign(tnevt,"N",ditchDown(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-1],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",ditchUp(tmp_pitch[j],tmp_type[j][tmp_type[j].size()-2],curKeyFifth),ss.str());
					evts.push_back(tnevt);
					tnevt=Assign(tnevt,"N",tmp_pitch[j],ss.str());
					evts.push_back(tnevt);
				}//endif
			}//endfor j
			lastPositionPerVoice[nevt.voice]=evts.size()-1;
		}//endfor i
}//

//// Eliminate redundancies and sort nevtSeq, extract after-notes after trills
{
		int prevNum=evts.size();
		int NumOfVoices=part_voice.size();
		vector<vector<Fmt2Evt> > voice_nevtSeq(NumOfVoices);
		int largestStime=0;
		for(int i=0;i<evts.size();i+=1){
			voice_nevtSeq[evts[i].voice].push_back(evts[i]);
			if(evts[i].stime>largestStime){largestStime=evts[i].stime;}
		}//endfor i

		/// reducing rests and tremolos
		/// converting short-app after trills to after-notes
		for(int i=0;i<NumOfVoices;i+=1){
			if(voice_nevtSeq[i].size()==0){continue;}
			bool after_trill=false;

			if(voice_nevtSeq[i][0].eventtype=="chord"){
				for(int k=0;k<voice_nevtSeq[i][0].notetypes.size();k+=1){
					if(voice_nevtSeq[i][0].notetypes[k].find("Tr")!=string::npos){
						after_trill=true;
						break;
					}//endif
				}//endfor k
			}//endif
			for(int j=1;j<voice_nevtSeq[i].size();j+=1){
				if(voice_nevtSeq[i][j].eventtype=="chord"||voice_nevtSeq[i][j].eventtype=="rest"){
					after_trill=false;
				}//endif
				if(voice_nevtSeq[i][j].eventtype=="chord"){
					for(int k=0;k<voice_nevtSeq[i][j].notetypes.size();k+=1){
						if(voice_nevtSeq[i][j].notetypes[k].find("Tr")!=string::npos){
							after_trill=true;
							break;
						}//endif
					}//endfor k
				}//endif
				if(after_trill&&voice_nevtSeq[i][j].eventtype=="short-app"){
					voice_nevtSeq[i][j].eventtype="after-note";
				}//endif
				if(voice_nevtSeq[i][j-1].eventtype=="rest"&&voice_nevtSeq[i][j].eventtype=="rest"){
					voice_nevtSeq[i][j-1].dur+=voice_nevtSeq[i][j].dur;
					voice_nevtSeq[i].erase(voice_nevtSeq[i].begin()+j);
					j-=1;
          // vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
          // [20200703] modified by nishikimi
         continue;
          // ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
				}//endif
				if(voice_nevtSeq[i][j-1].eventtype=="tremolo"&&voice_nevtSeq[i][j].eventtype=="tremolo"
					&&voice_nevtSeq[i][j-1].sitches==voice_nevtSeq[i][j].sitches
					&&voice_nevtSeq[i][j-1].notetypes==voice_nevtSeq[i][j].notetypes){
					voice_nevtSeq[i][j-1].dur+=voice_nevtSeq[i][j].dur;
					voice_nevtSeq[i].erase(voice_nevtSeq[i].begin()+j);
					j-=1;
          // vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
          // [20200703] modified by nishikimi
         continue;
          // ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
				}//endif
			}//endfor j
		}//endfor i

		/// Sorting nevtSeq
		int curstime=evts[0].stime;
		vector<int> numPerVoice(NumOfVoices);
		vector<int> posPerVoice(NumOfVoices);
		for(int i=0;i<NumOfVoices;i+=1){
			numPerVoice[i]=voice_nevtSeq[i].size();
			posPerVoice[i]=0;
		}//endfor i
		evts.clear();
		bool ended=false;
		bool found;
		while(!ended){
			found=false;
			for(int i=0;i<NumOfVoices;i+=1){
				if(posPerVoice[i]<=numPerVoice[i]-1 && curstime==voice_nevtSeq[i][posPerVoice[i]].stime){
					evts.push_back(voice_nevtSeq[i][posPerVoice[i]]);
					posPerVoice[i]+=1;
					found=true;
					break;
				}//endif
			}//endfor i
			if(found){
				ended=true;
				for(int i=0;i<NumOfVoices;i+=1){
					if(posPerVoice[i]<=numPerVoice[i]-1){ended=false; break;}
				}//endfor i
			}else{
				curstime=largestStime+1;
				for(int i=0;i<NumOfVoices;i+=1){
					if(posPerVoice[i]>numPerVoice[i]-1){continue;}
					if(voice_nevtSeq[i][posPerVoice[i]].stime<curstime){curstime=voice_nevtSeq[i][posPerVoice[i]].stime;}
				}//endfor i
			}//endif
		}//endwhile
	//	assert(nevtSeq.size()==prevNum);//for cheking!
}//

		for(int i=0;i<evts.size();i+=1){
			evts[i].numNotes=evts[i].sitches.size();
			for(int j=0;j<evts[i].numNotes;j+=1){
				evts[i].notetypes[j]=evts[i].notetypes[j]+evts[i].AFInfo[j];
			}//endfor j
		}//endfor i

	}//end ConvertFromFmt1x





};//endclass Fmt2

#endif // FMT2_HPP
