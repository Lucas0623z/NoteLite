#ifndef FMT1X_HPP
#define FMT1X_HPP

#include<iostream>
#include<string>
#include<sstream>
#include<cmath>
#include<vector>
#include<fstream>
#include<cassert>
#include"BasicCalculation_v170122.hpp"
using namespace std;

inline string altername(string str){
	string out="";
	if(str=="0"){out="";
	}else if(str=="1"){out="#";
	}else if(str=="2"){out="##";
	}else if(str=="3"){out="###";
	}else if(str=="-1"){out="b";
	}else if(str=="-2"){out="bb";
	}else if(str=="-3"){out="bbb";
	}//endif
	return out;
}//end altername

inline char intToDitchclass(int i){
	if(i==1){return 'C';
	}else if(i==2){return 'D';
	}else if(i==3){return 'E';
	}else if(i==4){return 'F';
	}else if(i==5){return 'G';
	}else if(i==6){return 'A';
	}else if(i==7){return 'B';
	}else{
cout<<"Unknown int for ditchclass!"<<endl; return 'C';
	}//endif
};

inline int ditchclassToInt(char dc){
	if(dc=='C'){return 1;
	}else if(dc=='D'){return 2;
	}else if(dc=='E'){return 3;
	}else if(dc=='F'){return 4;
	}else if(dc=='G'){return 5;
	}else if(dc=='A'){return 6;
	}else if(dc=='B'){return 7;
	}else{
cout<<"Unknown ditchclass name!"<<endl; return 1;
	}//endif
};

inline string acc_norm(char dc,int curKeyFifth){
	if(curKeyFifth==0){
		return "";
	}else if(curKeyFifth>0){
		for(int i=1;i<=curKeyFifth;i+=1){
			if(dc==intToDitchclass((i*4-1+70)%7+1)){return "#";}
		}//endfor i
		return "";
	}else if(curKeyFifth<0){
		for(int i=1;i<=-1*curKeyFifth;i+=1){
			if(dc==intToDitchclass((i*3+4-1+70)%7+1)){return "b";}
		}//endfor i
		return "";
	}else{
		return "";
	}//endif
};

inline string ditchUp(string principal,char acc_rel,int curKeyFifth){
	char dc=intToDitchclass( (ditchclassToInt(principal[0])+7-1+1)%7+1 );
	int oct=principal[principal.size()-1]-'0';
	if(dc=='C'){oct+=1;}
	string acc="";
	if(acc_rel!='*'){
		if(acc_rel=='n'){acc="";
		}else if(acc_rel=='s'){acc="#";
		}else if(acc_rel=='S'){acc="##";
		}else if(acc_rel=='f'){acc="b";
		}else if(acc_rel=='F'){acc="bb";
		}//endif
	}else{
		acc=acc_norm(dc,curKeyFifth);
	}//endif
	stringstream ss;
	ss.str(""); ss<<dc<<acc<<oct;
	return ss.str();
};

inline string ditchDown(string principal,char acc_rel,int curKeyFifth){
	char dc=intToDitchclass( (ditchclassToInt(principal[0])+7-1-1)%7+1 );
	int oct=principal[principal.size()-1]-'0';
	if(dc=='B'){oct-=1;}
	string acc;
	if(acc_rel!='*'){
		if(acc_rel=='n'){acc="";
		}else if(acc_rel=='s'){acc="#";
		}else if(acc_rel=='S'){acc="##";
		}else if(acc_rel=='f'){acc="b";
		}else if(acc_rel=='F'){acc="bb";
		}//endif
	}else{
		acc=acc_norm(dc,curKeyFifth);
	}//endif
	stringstream ss;
	ss.str(""); ss<<dc<<acc<<oct;
	return ss.str();
};

class Fmt1xEvt{
public:
	int stime;
	string barnum;
	int part;
	int staff;
	int voice;
	string eventtype;//attributes / rest / chord
	int dur;
	int tieinfo;
	int numNotes;//=sitches.size()
	vector<string> sitches;//size = numNotes
	vector<string> notetypes;//size = numNotes
//	vector<int> notenums;//size = numNotes
	vector<string> fmt1IDs;//size = numNotes
	vector<int> ties;// = 0(def)/1 if the note is NOT/is tied with a previous note. (Used only if tieinfo > 0) (size = numNotes) 
	string info;//used for type "attributes"

	vector<string> text;//size=numNotes (usually lyrics)

};//end class Fmt1xEvent

class LessFmt1xEvt{
public:
	bool operator()(const Fmt1xEvt& a, const Fmt1xEvt& b){
		if(a.stime < b.stime){
			return true;
		}else{//if a.stime >= b.stime
			return false;
		}//endif
	}//end operator()

};//end class LessFmt1xEvt
//stable_sort(Fmt1xEvts.begin(), Fmt1xEvts.end(), LessFmt1xEvt());



class Fmt1x{
public:
	int TPQN;
	vector<Fmt1xEvt> evts;
	vector<string> comments;

	void ReadFile(string filename){
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;

		evts.clear();
		comments.clear();

		ifstream ifs(filename.c_str());
		if(!ifs.is_open()){cout<<"File not found: "<<filename<<endl; assert(false);}
		Fmt1xEvt evt;
		while(ifs>>s[0]){
			if(s[0][0]=='/'||s[0][0]=='#'){
				if(s[0]=="//TPQN:"){
					ifs>>TPQN;
					getline(ifs,s[99]);
				}else if(s[0]=="//Fmt1xVersion:"){
					ifs>>s[1];
					if(s[1]!="170104"){
						cout<<"Warning: The fmt1x version is not 170104!"<<endl;
					}//endif
					getline(ifs,s[99]);
				}else{
					getline(ifs,s[99]);
					comments.push_back(s[99]);
				}//endif
				continue;
			}//endif
			evt.stime=atoi(s[0].c_str());
			ifs>>evt.barnum>>evt.part>>evt.staff>>evt.voice>>evt.eventtype;
			evt.sitches.clear(); evt.notetypes.clear(); evt.fmt1IDs.clear(); evt.ties.clear();
			evt.info="";
			if(evt.eventtype=="attributes"){
				getline(ifs,evt.info);
				evt.info+="\n";
			}else if(evt.eventtype=="rest"||evt.eventtype=="chord"||evt.eventtype=="tremolo-s"||evt.eventtype=="tremolo-e"||evt.eventtype=="tremolo-m"){
				ifs>>evt.dur>>evt.tieinfo>>evt.numNotes;
				for(int j=0;j<evt.numNotes;j+=1){ifs>>s[8]; evt.sitches.push_back(s[8]);}//endfor j
				for(int j=0;j<evt.numNotes;j+=1){ifs>>s[8]; evt.notetypes.push_back(s[8]);}//endfor j
				for(int j=0;j<evt.numNotes;j+=1){ifs>>s[8]; evt.fmt1IDs.push_back(s[8]);}//endfor j
				for(int j=0;j<evt.numNotes;j+=1){ifs>>v[8]; evt.ties.push_back(v[8]);}//endfor j
				getline(ifs,s[99]);
			}else{
				getline(ifs,s[99]);
				continue;
			}//endif
			evts.push_back(evt);
		}//endwhile
		ifs.close();

		//cout<<evts.size()<<endl;

	}//end ReadFile

	void WriteFile(string filename){
		ofstream ofs(filename.c_str());
		ofs<<"//TPQN: "<<TPQN<<"\n";
		ofs<<"//Fmt1xVersion: "<<"170104\n";
		for(int i=0;i<comments.size();i+=1){
			ofs<<"// "<<comments[i]<<"\n";
		}//endfor i
		for(int i=0;i<evts.size();i+=1){
			ofs<<evts[i].stime<<"\t"<<evts[i].barnum<<"\t"<<evts[i].part<<"\t"<<evts[i].staff<<"\t"<<evts[i].voice<<"\t"<<evts[i].eventtype;
			if(evts[i].eventtype=="attributes"){
				ofs<<evts[i].info;
				continue;
			}//endif
			ofs<<"\t"<<evts[i].dur<<"\t"<<evts[i].tieinfo<<"\t"<<evts[i].numNotes<<"\t";
			for(int j=0;j<evts[i].sitches.size();j+=1){
				ofs<<evts[i].sitches[j]<<"\t";
			}//endfor j
			for(int j=0;j<evts[i].notetypes.size();j+=1){
				ofs<<evts[i].notetypes[j]<<"\t";
			}//endfor j
			for(int j=0;j<evts[i].fmt1IDs.size();j+=1){
				ofs<<evts[i].fmt1IDs[j]<<"\t";
			}//endfor j
			for(int j=0;j<evts[i].ties.size();j+=1){
				ofs<<evts[i].ties[j]<<"\t";
			}//endfor j
			ofs<<"\n";
		}//endfor i
		ofs.close();
	}//end WriteFile

	void ReadMusicXML(string filename){
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;

		evts.clear();
		comments.clear();

		ifstream ifs(filename.c_str());
		if(!ifs.is_open()){cout<<"File not found: "<<filename<<endl; assert(false);}
		string all;
		while(!ifs.eof()){
			getline(ifs,s[99]);
			all+=s[99];
		}//endwhile
		ifs.close();

		vector<string> events;
		vector<int> depths;
		vector<bool> inout;
{
		bool isInBracket=false;
		int depth=0;
		for(int i=0;i<all.size();i+=1){
			if(all[i]=='<'){
				isInBracket=true;
				if(all[i+1]=='/'){depth-=1;
				}else if(all[i+1]=='!' || all[i+1]=='?'){;
				}else{depth+=1;
				}//endif
				events.push_back(s[0]);
				depths.push_back(depth);
				inout.push_back(false);
				s[0]="";
				continue;
			}else if(all[i]=='>'){
				isInBracket=false;
				if(all[i-1]=='/'){depth-=1;}
				events.push_back(s[0]);
				depths.push_back(depth);
				inout.push_back(true);
				s[0]="";
				continue;
			}//endif
			s[0]+=all[i];
		}//endfor i
}//

{
		vector<string> prev_events(events);
		vector<int> prev_depths(depths);
		vector<bool> prev_inout(inout);
		events.clear();
		depths.clear();
		inout.clear();
		for(int i=0;i<prev_events.size();i+=1){
			DeleteHeadSpace(prev_events[i]);
			if(prev_events[i]=="" || isspace(prev_events[i][0])!=0){continue;}
			if(prev_inout[i]){
				if(prev_events[i][0]!='/'&&prev_events[i][0]!='!'&&prev_events[i][0]!='?'){
					prev_depths[i]-=1;
					if(prev_events[i][prev_events[i].size()-1]=='/'){
						prev_depths[i]+=1;
					}//endif
				}//endif
			}//endif
			events.push_back(prev_events[i]);
			depths.push_back(prev_depths[i]);
			inout.push_back(prev_inout[i]);
		}//endfor i
}//

		TPQN=32;
{
		vector<int> divs;
		for(int i=1;i<events.size();i+=1){
			if(depths[i]==4&&UnspaceString(events[i])[0]=="divisions"){
				divs.push_back(atoi(events[i+1].c_str()));
			}//endif
		}//endfor i
		TPQN=divs[0];
		for(int i=1;i<divs.size();i+=1){
			TPQN=lcm(TPQN,divs[i]);
		}//endfor i
//cout<<"TPQN = "<<TPQN<<endl;
}//

		Fmt1xEvt evt;
		bool notein=false;
		bool backupin=false;
		bool forwardin=false;
		bool pitchin=false;//also used for unpitched notes
		bool isChord=false;
		string sitch,text;
		string type,arpinfo,ferinfo;
		int tie;
		int curPart=1;
		int curdivision;
		int cumulativeStime=0;
		int maxcumulativeStime=cumulativeStime;
		int time_num=4, time_den=4;
		int barDur=(time_num*TPQN*4)/time_den;
		int curKeyFifth=0;
		int clefNumToBeSpecified=0;
		string curKeyMode="major";
		int curNumOfStaves=1;
		string curMeasureNumPrinted="0";
		vector<string> curClefLab;
		vector<int> curClefOctChange;
		curClefLab.push_back("G2");
		curClefOctChange.push_back(0);
		v[0]=0;
		int notenum;
		string trem;
		string curScorePart="P0";
		string curInstrumentName,curPartName;

		for(int i=1;i<events.size();i+=1){
//cout<<i<<"\t"<<depths[i]<<"\t"<<events[i]<<endl;

			string eventTag=UnspaceString(events[i])[0];

			if(depths[i]==1&&eventTag=="part"){
				s[0]=UnspaceString(events[i])[1];
				s[0]=s[0].substr(s[0].find("\"")+2);//if '+2' delete 'P' in 'P1' etc.
				s[0]=s[0].substr(0,s[0].find("\""));
				curPart=atoi(s[0].c_str());
				cumulativeStime=0;
				maxcumulativeStime=cumulativeStime;
				curNumOfStaves=1;
				curClefLab.assign(curNumOfStaves,"G4");
				curClefOctChange.assign(curNumOfStaves,0);

			}else if(depths[i]==2&&eventTag=="score-part"){
				s[0]=UnspaceString(events[i])[1];
				s[0]=s[0].substr(s[0].find("\"")+1);
				s[0]=s[0].substr(0,s[0].find("\""));
				curScorePart=s[0];
				curInstrumentName="Unknown";
				curPartName="Unknown";
			}else if(depths[i]==3&&eventTag=="part-name"){
				curPartName=events[i+1];
			}else if(depths[i]==4&&eventTag=="instrument-name"){
				curInstrumentName=events[i+1];
			}else if(depths[i]==2&&eventTag=="/score-part"){
				comments.push_back("Instrument:\t"+curScorePart+"\t"+curInstrumentName);
				comments.push_back("Part-name:\t"+curScorePart+"\t"+curPartName);

			}else if(depths[i]==4&&eventTag=="divisions"){
				curdivision=atoi(events[i+1].c_str());
				barDur=(time_num*TPQN*4)/time_den;
			}else if(depths[i]==5&&eventTag=="fifths"){
				curKeyFifth=atoi(events[i+1].c_str());
			}else if(depths[i]==5&&eventTag=="mode"){
				curKeyMode=events[i+1];
			}else if(depths[i]==5&&eventTag=="beats"){
				time_num=atoi(events[i+1].c_str());
				barDur=(time_num*TPQN*4)/time_den;
			}else if(depths[i]==5&&eventTag=="beat-type"){
				time_den=atoi(events[i+1].c_str());
				barDur=(time_num*TPQN*4)/time_den;
			}else if(depths[i]==4&&eventTag=="staves"){
				curNumOfStaves=atoi(events[i+1].c_str());
				curClefLab.assign(curNumOfStaves,"G4");
				curClefOctChange.assign(curNumOfStaves,0);
			}else if(depths[i]==4&&eventTag=="clef"){
				vector<string> vstmp=UnspaceString(events[i]);
				if(vstmp.size()==1){
					clefNumToBeSpecified=0;
				}else{
					clefNumToBeSpecified=0;
					for(int ik=0;ik<vstmp.size();ik++){
						if(vstmp[ik].find("number")==string::npos){continue;}
						s[0]=vstmp[ik];
						s[0]=s[0].substr(s[0].find("number")+8);
						s[0]=s[0].substr(0,s[0].find("\""));
						clefNumToBeSpecified=atoi(s[0].c_str())-1;
					}//endfor ik
				}//endif
			}else if(depths[i]==5&&eventTag=="sign"){
				curClefLab[clefNumToBeSpecified]=events[i+1];
				curClefOctChange[clefNumToBeSpecified]=0;
			}else if(depths[i]==5&&eventTag=="line"){
				curClefLab[clefNumToBeSpecified]+=events[i+1];
			}else if(depths[i]==5&&eventTag=="clef-octave-change"){
				curClefOctChange[curClefOctChange.size()-1]=atoi(events[i+1].c_str());
			}else if(depths[i]==2&&eventTag=="measure"){
				notenum=0;
				s[0]="NA";
				for(int k=1;k<UnspaceString(events[i]).size();k+=1){
					if(UnspaceString(events[i])[k].find("number")!=string::npos){
						s[0]=UnspaceString(events[i])[k];
						s[0]=s[0].substr(s[0].find("\"")+1);
						s[0]=s[0].substr(0,s[0].find("\""));
						break;
					}//endif
				}//endfor k
				curMeasureNumPrinted=s[0];
				if(maxcumulativeStime!=cumulativeStime){
					cumulativeStime=maxcumulativeStime;
					ss.str("");
					ss<<"//warning: maxcumulativeStime!=cumulativeStime at bar onset at "<<s[0]<<"\t"<<cumulativeStime;
//cout<<"//warning: maxcumulativeStime!=cumulativeStime at bar onset at "<<s[0]<<"\t"<<cumulativeStime<<endl;;
//					comments.push_back(ss.str());
				}//endif
			}else if(depths[i]==3&&eventTag=="backup"){
				backupin=true;
			}else if(depths[i]==3&&eventTag=="forward"){
				forwardin=true;
			}else if(depths[i]==3&&eventTag=="note"){
				notenum+=1;
				notein=true;
				isChord=false;
				evt.stime=cumulativeStime;
				evt.barnum=curMeasureNumPrinted;
				evt.part=curPart;

				evt.staff=1;
				evt.voice=1;
				evt.dur=0;
				evt.tieinfo=0;
				tie=0;
				trem="";
				sitch="C4";
				type="N";
				arpinfo="";
				ferinfo="";
				text="";
				v[0]+=1;
			}else if(depths[i]==3&&eventTag=="/attributes"){
				evt.stime=cumulativeStime;
				evt.barnum=curMeasureNumPrinted;
				evt.part=curPart;
				evt.staff=1;
				evt.voice=1;
				evt.eventtype="attributes";
				evt.dur=0;
				evt.tieinfo=0;
				evt.numNotes=0;
				evt.sitches.clear();
				evt.notetypes.clear();
				evt.fmt1IDs.clear();
				evt.text.clear();

				ss.str("");
				ss<<"\t"<<TPQN<<"\t"<<curKeyFifth<<"\t"<<curKeyMode<<"\t"<<time_num<<"\t"<<time_den<<"\t";
				ss<<curNumOfStaves<<"\t";
				for(int j=0;j<curNumOfStaves;j+=1){
					ss<<curClefLab[j]<<"\t"<<curClefOctChange[j]<<"\t";
				}//endfor j
				ss<<"\n";
				evt.info=ss.str();

				evts.push_back(evt);
			}//endif

			if(notein){
				if(depths[i]==4&&eventTag=="chord/"){
					isChord=true;
					evt.stime-=evts[evts.size()-1].dur;
					cumulativeStime-=evts[evts.size()-1].dur;
				}else if(depths[i]==4&&events[i].find("rest")!=string::npos){
					sitch="rest";
				}else if(depths[i]==4&&events[i].find("pitch")!=string::npos){//also used for unpitched notes
					pitchin=true;
				}else if(depths[i]==4&&eventTag=="staff"){
					evt.staff=atoi(events[i+1].c_str());
				}else if(depths[i]==4&&eventTag=="voice"){
					evt.voice=atoi(events[i+1].c_str());
				}else if(depths[i]==4&&eventTag=="duration"){
					evt.dur=(atoi(events[i+1].c_str())*TPQN)/curdivision;
					cumulativeStime+=evt.dur;
					if(maxcumulativeStime<cumulativeStime){maxcumulativeStime=cumulativeStime;}
				}else if(depths[i]==4&&eventTag=="tie"){
					if(UnspaceString(events[i])[1].find("stop")!=string::npos){tie+=2;}//endif
					if(UnspaceString(events[i])[1].find("start")!=string::npos){tie+=1;}//endif
				}else if(depths[i]==5&&eventTag=="text"){
					text=events[i+1];
				}else if(depths[i]==5&&eventTag=="ornaments"){
					if(UnspaceString(events[i+1])[0]=="wavy-line"){
					}else if(UnspaceString(events[i+1])[0]=="tremolo"){
						type="N";
						if(UnspaceString(events[i+1])[1].find("start")!=string::npos){
							trem="tremolo-s";
						}else if(UnspaceString(events[i+1])[1].find("stop")!=string::npos){
							trem="tremolo-e";
						}else{
							trem="tremolo-m";
						}//endif			
					}else{
						type=UnspaceString(events[i+1])[0];
						type+="**";
					}//endif
				}else if(depths[i]==6&&eventTag=="accidental-mark"){
					v[10]=-1;//accMarkPlace
					for(int j=0;j<UnspaceString(events[i]).size();j+=1){
						if(UnspaceString(events[i])[j].find("above")!=string::npos){
							v[10]=2; break;
						}else if(UnspaceString(events[i])[j].find("below")!=string::npos){
							v[10]=1; break;
						}//endif
					}//endfor j
					if(v[10]<0){
						v[10]=2;
						if(type[type.size()-2]!='*'){v[10]=1;}
					}//endif
					if(events[i+1]=="natural"){type[type.size()-v[10]]='n';
					}else if(events[i+1]=="sharp"){type[type.size()-v[10]]='s';
					}else if(events[i+1]=="double-sharp"){type[type.size()-v[10]]='S';
					}else if(events[i+1]=="flat"){type[type.size()-v[10]]='f';
					}else if(events[i+1]=="flat-flat"){type[type.size()-v[10]]='F';
					}//endif
				}else if(depths[i]==5&&eventTag=="arpeggiate"){
					v[10]=UnspaceString(events[i]).size();
					for(int j=1;j<v[10];j+=1){
						if(UnspaceString(events[i])[j].find("number")!=string::npos){
							s[0]=UnspaceString(events[i])[j];
							s[0]=s[0].substr(s[0].find("num")+8,s[0].size());
							arpinfo="Arp"+s[0].substr(0,s[0].find("\""));
						}//endif
					}//endfor j
				}else if(depths[i]==5&&eventTag=="fermata"){
					ferinfo="Fer";
				}//endif
				if(pitchin){
					if(depths[i]==5&&eventTag=="step"){
						if(events[i+2]=="/step"){
							sitch[0]=events[i+1][0];
						}//endif
					}else if(depths[i]==5&&eventTag=="octave"){
						sitch[sitch.size()-1]=events[i+1][0];
					}else if(depths[i]==5&&eventTag=="alter"){
						ss.str("");
						ss<<sitch[0]<<altername(events[i+1])<<sitch[sitch.size()-1];
						sitch=ss.str();
					}else if(depths[i]==5&&eventTag=="display-step"){
						if(events[i+2]=="/display-step"){
							sitch[0]=events[i+1][0];
						}//endif
					}else if(depths[i]==5&&eventTag=="display-octave"){
						sitch[sitch.size()-1]=events[i+1][0];
					}else if(depths[i]==5&&eventTag=="display-alter"){
						ss.str("");
						ss<<sitch[0]<<altername(events[i+1])<<sitch[sitch.size()-1];
						sitch=ss.str();
					}else if(depths[i]==4&&(eventTag=="pitch/"||eventTag=="/unpitched")){
						pitchin=false;
					}//endif
				}//endif
			}//endif

			if(backupin){
				if(depths[i]==4&&eventTag=="duration"){
					cumulativeStime-=(atoi(events[i+1].c_str())*TPQN)/curdivision;
				}else if(depths[i]==3&&eventTag=="/backup"){
					backupin=false;
				}//endif
			}//endif
			if(forwardin){
				if(depths[i]==4&&eventTag=="duration"){
					cumulativeStime+=(atoi(events[i+1].c_str())*TPQN)/curdivision;
					if(maxcumulativeStime<cumulativeStime){maxcumulativeStime=cumulativeStime;}
				}else if(depths[i]==3&&eventTag=="/forward"){
					forwardin=false;
				}//endif
			}//endif

			if(depths[i]==3&&eventTag=="/note"){
				if(!isChord){
					ss.str("");
					if(sitch=="rest"){
						evt.eventtype="rest";
						ss<<"N";
					}else if(trem!=""){
						evt.eventtype=trem;
						ss<<type<<"."<<arpinfo<<"."<<ferinfo;
					}else{//standard chord
						evt.eventtype="chord";
						ss<<type<<"."<<arpinfo<<"."<<ferinfo;
					}//endif
					evt.numNotes=1;
					evt.sitches.clear();
					evt.sitches.push_back(sitch);

					evt.notetypes.clear();
					evt.notetypes.push_back(ss.str());
					evt.fmt1IDs.clear();
					ss.str("");
					ss<<"P"<<evt.part<<"-"<<evt.barnum<<"-"<<notenum;
					evt.fmt1IDs.push_back(ss.str());
					evt.ties.clear();
					evt.ties.push_back( ((tie>1)? 1:0) );
					evt.tieinfo=tie;

					evt.text.clear();
					evt.text.push_back(text);

					evts.push_back(evt);
				}else{
					ss.str("");
					ss<<type<<"."<<arpinfo<<"."<<ferinfo;
					evts[evts.size()-1].numNotes+=1;
					evts[evts.size()-1].sitches.push_back(sitch);
					evts[evts.size()-1].notetypes.push_back(ss.str());
					ss.str("");
					ss<<"P"<<evts[evts.size()-1].part<<"-"<<evts[evts.size()-1].barnum<<"-"<<notenum;
					evts[evts.size()-1].fmt1IDs.push_back(ss.str());
					evts[evts.size()-1].ties.push_back( ((tie>1)? 1:0) );
					if(tie%2==1 && evts[evts.size()-1].tieinfo%2==0){
						evts[evts.size()-1].tieinfo+=1;
					}//enduf
					if(tie/2==1 && evts[evts.size()-1].tieinfo/2==0){
						evts[evts.size()-1].tieinfo+=2;
					}//enduf
					evts[evts.size()-1].text.push_back(text);

				}//endif
				notein=false;
			}//endif
		}//endfor i

	}//end ReadMusicXML

	void Sort(){
		stable_sort(evts.begin(), evts.end(), LessFmt1xEvt());
	}//end Sort

};//endclass Fmt1x


#endif // FMT1X_HPP
