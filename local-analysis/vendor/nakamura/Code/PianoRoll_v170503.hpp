#ifndef PIANOROLL_HPP
#define PIANOROLL_HPP

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
#include"BasicCalculation_v170122.hpp"
#include"BasicPitchCalculation_v170101.hpp"
#include"Midi_v170101.hpp"
using namespace std;

class PianoRollEvt{
public:
	string ID;
	double ontime;
	double offtime;
	string sitch;//spelled pitch
	int pitch;//integral pitch
	int onvel;
	int offvel;
	int channel;
	double endtime;//Including pedalling. Not written in spr/ipr files.
	string label;

	int ext1;//extended variable 1
	double extVal1;
	double extVal2;

	PianoRollEvt(){
		ID="0";
		endtime=0;
		label="-";
		ext1=0;
		extVal1=0;
		extVal2=0;
		channel=0;
		onvel=80;
		offvel=80;
	}//end PianoRollEvt
	~PianoRollEvt(){}//end ~PianoRollEvt

	void Print(){
cout<<ID<<"\t"<<ontime<<"\t"<<offtime<<"\t"<<sitch<<"\t"<<pitch<<"\t"<<onvel<<"\t"<<offvel<<"\t"<<channel<<"\t"<<label<<endl;
	}//end Print

};//end class PianoRollEvt

class LessPianoRollEvt{
public:
	bool operator()(const PianoRollEvt& a, const PianoRollEvt& b){
		if(a.ontime < b.ontime){
			return true;
		}else if(a.ontime==b.ontime){
			if(a.pitch<b.pitch){
				return true;
			}else{
				return false;
			}//endif
		}else{//if a.ontime > b.ontime
			return false;
		}//endif
	}//end operator()

};//end class LessPianoRollEvt
//stable_sort(PianoRollEvts.begin(), PianoRollEvts.end(), LessPianoRollEvt());

class LessPitchPianoRollEvt{
public:
	bool operator()(const PianoRollEvt& a, const PianoRollEvt& b){
		if(a.pitch < b.pitch){
			return true;
		}else{//if
			return false;
		}//endif
	}//end operator()
};//end class LessPitchPianoRollEvt
//stable_sort(PianoRollEvts.begin(), PianoRollEvts.end(), LessPitchPianoRollEvt());

class PedalEvt{
public:
	string type;//SosPed, SusPed, SofPed
	double time;
	int value;
	int channel;

	PedalEvt(){	}//end PedalEvt
	~PedalEvt(){}//end ~PedalEvt
};//end class PedalEvt

class LessPedalEvt{
public:
	bool operator()(const PedalEvt& a, const PedalEvt& b){
		if(a.time < b.time){
			return true;
		}else if(a.time==b.time){
			if(a.value<b.value){
				return true;
			}else{
				return false;
			}//endif
		}else{//if a.time > b.time
			return false;
		}//endif
	}//end operator()
};//end class LessPedalEvt
//stable_sort(PedalEvts.begin(), PedalEvts.end(), LessPedalEvt());

class PedalInterval{
public:
	string type;//SosPed, SusPed, SofPed
	double ontime;
	double offtime;
	int channel;

	PedalInterval(){}//end PedalInterval
	~PedalInterval(){}//end ~PedalInterval
};//end class PedalInterval

class ProgramChangeEvt{
public:
	double time;
	int value;
	int channel;
};//end class ProgramChangeEvt


class PianoRoll{
public:
	vector<string> comments;
	vector<PianoRollEvt> evts;
	vector<PedalEvt> pedals;
	vector<PedalInterval> pedalIntervals;//Not written in files
	vector<ProgramChangeEvt> programChangeEvts;
	vector<int> programChangeData;

	PianoRoll(){
		programChangeData.assign(16,0);
	}//end PianoRoll
	PianoRoll(string filename){
		ReadFileSpr(filename);
		programChangeData.assign(16,0);
	}//end PianoRoll
	~PianoRoll(){}//end ~PianoRoll

	void Clear(){
		comments.clear();
		evts.clear();
		pedals.clear();
		pedalIntervals.clear();
		programChangeEvts.clear();
	}//end Clear

	void ReadFileSpr(string sprFile){
		Clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		PianoRollEvt evt;
		PedalEvt pedal;
		ifstream ifs(sprFile.c_str());
		while(ifs>>s[0]){
			if(s[0][0]=='/'){
				getline(ifs,s[99]);
				ss.str("");
				ss<<s[0]<<" "<<s[99];
				comments.push_back(ss.str());
				continue;
			}else if(s[0][0]=='#'){
				if(s[0]=="#SusPed"){
					pedal.type="SusPed";
					ifs>>pedal.time>>pedal.value>>pedal.channel;
					pedals.push_back(pedal);
				}else if(s[0]=="#SosPed"){
					pedal.type="SosPed";
					ifs>>pedal.time>>pedal.value>>pedal.channel;
					pedals.push_back(pedal);
				}else if(s[0]=="#SofPed"){
					pedal.type="SofPed";
					ifs>>pedal.time>>pedal.value>>pedal.channel;
					pedals.push_back(pedal);
				}else if(s[0]=="#ProgramChange"){
					ProgramChangeEvt pcEvt;
					ifs>>pcEvt.time>>pcEvt.value>>pcEvt.channel;
					programChangeEvts.push_back(pcEvt);
				}else{
				}//endif
					getline(ifs,s[99]); continue;
			}//endif
			evt.ID=s[0];
			ifs>>evt.ontime>>evt.offtime>>evt.sitch>>evt.onvel>>evt.offvel>>evt.channel;
			evt.pitch=SitchToPitch(evt.sitch);
			evts.push_back(evt);
			getline(ifs,s[99]);
		}//endwhile
		ifs.close();

		SetPedalIntervals();
		SetEndtimes();

	}//end ReadFileSpr


	void ReadFileIpr(string iprFile){//Note that pitch->sitch is not unique!
		Clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		PianoRollEvt evt;
		PedalEvt pedal;
		ifstream ifs(iprFile.c_str());
		while(ifs>>s[0]){
			if(s[0][0]=='/'){
				getline(ifs,s[99]);
				ss.str("");
				ss<<s[0]<<" "<<s[99];
				comments.push_back(ss.str());
				continue;
			}else if(s[0][0]=='#'){
				if(s[0]=="#SusPed"){
					pedal.type="SusPed";
					ifs>>pedal.time>>pedal.value>>pedal.channel;
					pedals.push_back(pedal);
				}else if(s[0]=="#SosPed"){
					pedal.type="SosPed";
					ifs>>pedal.time>>pedal.value>>pedal.channel;
					pedals.push_back(pedal);
				}else if(s[0]=="#SofPed"){
					pedal.type="SofPed";
					ifs>>pedal.time>>pedal.value>>pedal.channel;
					pedals.push_back(pedal);
				}else if(s[0]=="#ProgramChange"){
					ProgramChangeEvt pcEvt;
					ifs>>pcEvt.time>>pcEvt.value>>pcEvt.channel;
					programChangeEvts.push_back(pcEvt);
				}else{
				}//endif
					getline(ifs,s[99]); continue;
			}//endif

			evt.ID=s[0];
			ifs>>evt.ontime>>evt.offtime>>evt.pitch>>evt.onvel>>evt.offvel>>evt.channel;
			evt.sitch=PitchToSitch(evt.pitch);
			evts.push_back(evt);
			getline(ifs,s[99]);
		}//endwhile
		ifs.close();

		SetPedalIntervals();
		SetEndtimes();

	}//end ReadFileIpr

	void SetPedalIntervals(){
		pedalIntervals.clear();
		PedalInterval pedalInt;//type,ontime,offtime,channel
		vector<PedalInterval> pendingIntervals;
		int onoffthres=63;//or 0??
		for(int i=0;i<pedals.size();i+=1){
			if(pedals[i].value<=onoffthres){
				int pendingPos=-1;
				for(int k=0;k<pendingIntervals.size();k+=1){
					if(pendingIntervals[k].channel==pedals[i].channel && pendingIntervals[k].type==pedals[i].type){
						pendingPos=k;
						break;
					}//endif
				}//endfor k
				if(pendingPos>=0){
					pendingIntervals[pendingPos].offtime=pedals[i].time;
					pedalIntervals.push_back(pendingIntervals[pendingPos]);
					pendingIntervals.erase(pendingIntervals.begin()+pendingPos);
				}//endif
			}else if(pedals[i].value>onoffthres){
				int pendingPos=-1;
				for(int k=0;k<pendingIntervals.size();k+=1){
					if(pendingIntervals[k].channel==pedals[i].channel && pendingIntervals[k].type==pedals[i].type){
						pendingPos=k;
						break;
					}//endif
				}//endfor k
				if(pendingPos<0){
					pedalInt.type=pedals[i].type;
					pedalInt.ontime=pedals[i].time;
					pedalInt.offtime=pedalInt.ontime+10;// Cutoff = 10 sec
					pedalInt.channel=pedals[i].channel;
					pendingIntervals.push_back(pedalInt);
				}else{//pendingPos>=0
					//Do nothing
				}//endif
			}//endif
		}//endfor i
		for(int k=0;k<pendingIntervals.size();k+=1){
			pedalIntervals.push_back(pendingIntervals[k]);
		}//endfor k
	}//end SetPedalIntervals

	void SetEndtimes(){//Currently use only sustain pedals
		for(int n=0;n<evts.size();n+=1){
			evts[n].endtime=evts[n].offtime;
			//pedalInterval s.t. pedal.ontime <= note.offtime < pedal.offtime
			//If sostenuto pedal, further require pedal.ontime >= note.ontime
			// -> Set endtime = pedal.offtime
			// If found next onset with next.ontime < pedal.offtime
			// -> Set endtime = next.ontime
			for(int k=0;k<pedalIntervals.size();k+=1){
				if(pedalIntervals[k].type!="SusPed" && pedalIntervals[k].type!="SosPed"){continue;}
				if(pedalIntervals[k].channel!=evts[n].channel){continue;}
				if(pedalIntervals[k].ontime<=evts[n].offtime && pedalIntervals[k].offtime>evts[n].offtime){
					if(pedalIntervals[k].type=="SosPed" && pedalIntervals[k].ontime<evts[n].ontime){continue;}
					evts[n].endtime=pedalIntervals[k].offtime;
					break;
				}//endif
			}//endfor k
			for(int m=n+1;m<evts.size();m+=1){
				if(evts[m].ontime>=evts[n].endtime){break;}
				if(evts[m].channel!=evts[n].channel){continue;}
				if(evts[m].pitch!=evts[n].pitch){continue;}
				evts[n].endtime=evts[m].ontime;
				break;
			}//endfor m
		}//endfor n
	}//end SetEndtimes

	void ReadFileOldSpr(string sprFile){
		Clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		PianoRollEvt evt;
		ifstream ifs(sprFile.c_str());
		while(ifs>>s[0]){
			if(s[0][0]=='/'||s[0][0]=='#'){
				getline(ifs,s[99]);
				ss.str("");
				ss<<s[0]<<" "<<s[99];
				comments.push_back(ss.str());
				continue;
			}//endif
			evt.ID=s[0];
			ifs>>evt.ontime>>evt.offtime>>evt.sitch>>evt.onvel>>evt.offvel>>evt.channel;
			evt.sitch=OldSitchToSitch(evt.sitch);
			evt.pitch=SitchToPitch(evt.sitch);
			evts.push_back(evt);
			getline(ifs,s[99]);
		}//endwhile
		ifs.close();
	}//end ReadFileOldSpr

	void ReadMIDIFile(string midiFile){
		Clear();
		Midi midi;
		midi.ReadFile(midiFile);

		int onPosition[16][128];
		for(int i=0;i<16;i+=1)for(int j=0;j<128;j+=1){onPosition[i][j]=-1;}//endfor i,j
		PianoRollEvt evt;
		int curChan;

		for(int n=0;n<midi.content.size();n+=1){

			if(midi.content[n].mes[0]>=128 && midi.content[n].mes[0]<160){//note-on or note-off event

				curChan=midi.content[n].mes[0]%16;
				if(midi.content[n].mes[0]>=144 && midi.content[n].mes[2]>0){//note-on
					if(onPosition[curChan][midi.content[n].mes[1]]>=0){
// cout<<"Warning: (Double) note-on event before a note-off event "<<PitchToSitch(midi.content[n].mes[1])<<endl;
						evts[onPosition[curChan][midi.content[n].mes[1]]].offtime=midi.content[n].time;
						evts[onPosition[curChan][midi.content[n].mes[1]]].offvel=-1;
					}//endif
					onPosition[curChan][midi.content[n].mes[1]]=evts.size();
					evt.channel=curChan;
					evt.sitch=PitchToSitch(midi.content[n].mes[1]);
					evt.pitch=midi.content[n].mes[1];
					evt.onvel=midi.content[n].mes[2];
					evt.offvel=0;
					evt.ontime=midi.content[n].time;
					evt.offtime=evt.ontime+0.1;
					evts.push_back(evt);
				}else{//note-off
					if(onPosition[curChan][midi.content[n].mes[1]]<0){
// cout<<"Warning: Note-off event before a note-on event "<<PitchToSitch(midi.content[n].mes[1])<<endl;
// cout<<midi.content[n].time<<endl;
						continue;
					}//endif
					evts[onPosition[curChan][midi.content[n].mes[1]]].offtime=midi.content[n].time;
					if(midi.content[n].mes[2]>0){
						evts[onPosition[curChan][midi.content[n].mes[1]]].offvel=midi.content[n].mes[2];
					}else{
						evts[onPosition[curChan][midi.content[n].mes[1]]].offvel=80;
					}//endif
					onPosition[curChan][midi.content[n].mes[1]]=-1;
				}//endif

			}else if(midi.content[n].mes[0]>=192 && midi.content[n].mes[0]<208){//Program change event

				ProgramChangeEvt pcEvt;
				pcEvt.time=midi.content[n].time;
				pcEvt.value=midi.content[n].mes[1];
				pcEvt.channel=midi.content[n].mes[0]-192;
				programChangeEvts.push_back(pcEvt);

			}//endif

		}//endfor n

		for(int i=0;i<16;i+=1)for(int j=0;j<128;j+=1){
			if(onPosition[i][j]>=0){
cout<<"Warning: Note without a note-off event"<<endl;
cout<<"ontime channel sitch : "<<evts[onPosition[i][j]].ontime<<"\t"<<evts[onPosition[i][j]].channel<<"\t"<<evts[onPosition[i][j]].sitch<<endl;
//				return;
			}//endif
		}//endfor i,j

		/// Extract pedal information
		PedalEvt pedal;
		for(int n=0;n<midi.content.size();n+=1){
			if(midi.content[n].mes[0]<176 || midi.content[n].mes[0]>=192){continue;}
			if(midi.content[n].mes[1]==64){
				pedal.type="SusPed";
				pedal.time=midi.content[n].time;
				pedal.value=midi.content[n].mes[2];
				pedal.channel=midi.content[n].mes[0]%16;
			}else if(midi.content[n].mes[1]==66){
				pedal.type="SosPed";
				pedal.time=midi.content[n].time;
				pedal.value=midi.content[n].mes[2];
				pedal.channel=midi.content[n].mes[0]%16;
			}else if(midi.content[n].mes[1]==67){
				pedal.type="SofPed";
				pedal.time=midi.content[n].time;
				pedal.value=midi.content[n].mes[2];
				pedal.channel=midi.content[n].mes[0]%16;
			}else{
				continue;
			}//endif
			pedals.push_back(pedal);
		}//endfor n

		for(int n=0;n<evts.size();n+=1){
			stringstream ss;
			ss.str(""); ss<<n;
			evts[n].ID=ss.str();
		}//endfor n

		SetPedalIntervals();
		SetEndtimes();

	}//end ReadMIDIFile

	void WriteFileSpr(string outputFile,bool pedalOn=false,bool extOn=false){
		ofstream ofs(outputFile.c_str());
		ofs<<"//Version: PianoRoll_v170101"<<"\n";
		for(int i=0;i<comments.size();i+=1){
			ofs<<comments[i]<<endl;
		}//endfor i
		for(int i=0;i<programChangeEvts.size();i+=1){
ofs<<"#ProgramChange "<<programChangeEvts[i].time<<"\t"<<programChangeEvts[i].value<<"\t"<<programChangeEvts[i].channel<<"\n";
		}//endfor i
		for(int n=0;n<evts.size();n+=1){
			PianoRollEvt evt=evts[n];
			ofs<<evt.ID<<"\t"<<fixed<<setprecision(6)<<evt.ontime<<"\t"<<evt.offtime<<"\t"<<evt.sitch<<"\t"<<evt.onvel<<"\t"<<evt.offvel<<"\t"<<evt.channel;
			if(extOn){
				ofs<<"\t"<<evt.endtime<<"\t"<<evt.ext1<<"\t"<<evt.extVal1<<"\t"<<evt.extVal2;
			}else if(pedalOn){
				ofs<<"\t"<<evt.endtime;
			}//endif
			ofs<<"\n";
		}//endfor n
		for(int n=0;n<pedals.size();n+=1){
			PedalEvt pedal=pedals[n];
			ofs<<"#"<<pedal.type<<"\t"<<pedal.time<<"\t"<<pedal.value<<"\t"<<pedal.channel<<"\n";
		}//endfor n
		ofs.close();
	}//end WriteFileSpr

	void WriteFileIpr(string outputFile,bool pedalOn=false){
		ofstream ofs(outputFile.c_str());
		ofs<<"//Version: PianoRoll_v170101"<<"\n";
		for(int i=0;i<comments.size();i+=1){
			ofs<<comments[i]<<endl;
		}//endfor i
		for(int i=0;i<programChangeEvts.size();i+=1){
ofs<<"#ProgramChange "<<programChangeEvts[i].time<<"\t"<<programChangeEvts[i].value<<"\t"<<programChangeEvts[i].channel<<"\n";
		}//endfor i
		for(int n=0;n<evts.size();n+=1){
			PianoRollEvt evt=evts[n];
			ofs<<evt.ID<<"\t"<<fixed<<setprecision(6)<<evt.ontime<<"\t"<<evt.offtime<<"\t"<<evt.pitch<<"\t"<<evt.onvel<<"\t"<<evt.offvel<<"\t"<<evt.channel;
			if(pedalOn){
				ofs<<"\t"<<evt.endtime;
			}//endif
			ofs<<"\n";
		}//endfor n
		for(int n=0;n<pedals.size();n+=1){
			PedalEvt pedal=pedals[n];
			ofs<<"#"<<pedal.type<<"\t"<<pedal.time<<"\t"<<pedal.value<<"\t"<<pedal.channel<<"\n";
		}//endfor n
		ofs.close();
	}//end WriteFileIpr

	void WriteMIDIFile(string filename){
		Midi midi;
		midi=ToMidi();
		midi.SetStrData();

		ofstream ofs;
		ofs.open(filename.c_str(), std::ios::binary);
		ofs<<midi.strData;
		ofs.close();
	}//end WriteMIDIFile

	Midi ToMidi(){
		Midi midi;
		midi.content.clear();
		midi.programChangeData=programChangeData;

		MidiMessage midiMes;
		for(int i=0;i<evts.size();i+=1){
			midiMes.time=evts[i].ontime;
			midiMes.mes.assign(3,0);
			midiMes.mes[0]=144+evts[i].channel;
			midiMes.mes[1]=evts[i].pitch;
			midiMes.mes[2]=evts[i].onvel;
			midi.content.push_back(midiMes);

			midiMes.time=evts[i].offtime;
			midiMes.mes.assign(3,0);
			midiMes.mes[0]=128+evts[i].channel;
			midiMes.mes[1]=evts[i].pitch;
			midiMes.mes[2]=((evts[i].offvel>0)? evts[i].offvel:80);
			midi.content.push_back(midiMes);
		}//endfor i

		for(int i=0;i<pedals.size();i+=1){
			midiMes.time=pedals[i].time;
			midiMes.mes.assign(3,0);
			midiMes.mes[0]=176+pedals[i].channel;
			if(pedals[i].type=="SusPed"){
				midiMes.mes[1]=64;
			}else if(pedals[i].type=="SosPed"){
				midiMes.mes[1]=66;
			}else if(pedals[i].type=="SofPed"){
				midiMes.mes[1]=67;
			}else{
				continue;
			}//endif
			midiMes.mes[2]=pedals[i].value;
			midi.content.push_back(midiMes);
		}//endfor i

		for(int i=0;i<programChangeEvts.size();i+=1){
			midiMes.time=programChangeEvts[i].time;
			midiMes.mes.assign(2,0);
			midiMes.mes[0]=192+programChangeEvts[i].channel;
			midiMes.mes[1]=programChangeEvts[i].value;
			midi.content.push_back(midiMes);
		}//endfor i

		stable_sort(midi.content.begin(),midi.content.end(),LessMidiMessage());
		return midi;
	}//end ToMidi

	void Sort(){
		stable_sort(evts.begin(), evts.end(), LessPianoRollEvt());
	}//end Sort

	void SetEndtimeToOfftime(){
		for(int n=0;n<evts.size();n+=1){
			evts[n].offtime=evts[n].endtime;
		}//endfor n
	}//end SetEndtimeToOfftime

	void Trim(double startTime,double endTime){
		for(int n=evts.size()-1;n>=0;n-=1){
			if(evts[n].ontime>endTime){
				evts.erase(evts.begin()+n);
				continue;
			}else if(evts[n].endtime<startTime){
				evts.erase(evts.begin()+n);
				continue;
			}//endif
			if(evts[n].ontime<startTime){
				evts[n].ontime=startTime;
			}//endif
			if(evts[n].offtime>endTime){
				evts[n].offtime=endTime;
			}//endif
			if(evts[n].endtime>endTime){
				evts[n].endtime=endTime;
			}//endif
		}//endfor n
	}//end Trim

	vector<double> GetPitchHistogram(){
		vector<double> ret;
		ret.assign(128,0);
		for(int n=0;n<evts.size();n++){
			if(evts[n].pitch<0){continue;}
			ret[evts[n].pitch]+=evts[n].offtime-evts[n].ontime;
		}//endfor n
		Normalize(ret);
		return ret;
	}//end GetPitchHistogram

};//end class PianoRoll

#endif // PIANOROLL_HPP

