#ifndef Hom_HPP
#define Hom_HPP

#include<iostream>
#include<fstream>
#include<string>
#include<sstream>
#include<vector>
#include<stdio.h>
#include<cmath>
#include<cassert>
#include"Fmt2_v170104.hpp"

using namespace std;

class HomEvt{
public:
	int stime;
	int endstime;
	int voice;
	string eventtype;
	int dur;
	int numNotes;
	vector<string> notetypes;//N or Tr etc.
	vector<string> sitches;//sitch content
	vector<string> fmt1IDs;//id in fmt1

	void Print(){
cout<<stime<<"\t"<<endstime<<"\t"<<voice<<"\t"<<eventtype<<"\t"<<dur<<"\t"<<numNotes;
		for(int i=0;i<numNotes;i+=1){cout<<"\t"<<sitches[i];}//endfor i
		for(int i=0;i<numNotes;i+=1){cout<<"\t"<<notetypes[i];}//endfor i
		for(int i=0;i<numNotes;i+=1){cout<<"\t"<<fmt1IDs[i];}//endfor i
cout<<endl;
	}//end Print

};//endclass Fmt2Evt
/*
class LessFmt2EvtStime{
public:
	bool operator()(const Fmt2Evt& a, const Fmt2Evt& b){ return a.stime < b.stime;}
};
//stable_sort(fmt2EvtSeq.begin(), fmt2EvtSeq.end(), LessFmt2EvtStime());
*/

class Hom{
public:
	vector<string> comments;
	vector<HomEvt> evts;
	int TPQN;

	void ReadFile(string filename){
		comments.clear();
		evts.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;

		HomEvt evt;
		ifstream ifs(filename.c_str());
		if(!ifs.is_open()){cout<<"File not found: "<<filename<<endl; assert(false);}
		while(ifs>>s[0]){
			if(s[0][0]=='/' || s[0][0]=='#'){
				if(s[0]=="//TPQN:"){
					ifs>>TPQN;
					getline(ifs,s[99]);
				}else if(s[0]=="//HomVersion:"){
					ifs>>s[1];
					if(s[1]!="170101"){
						cout<<"Warning: The hom version is not 170101!"<<endl;
					}//endif
					getline(ifs,s[99]);
				}else{
					getline(ifs,s[99]);
					comments.push_back(s[99]);
				}//endif
				continue;
			}//endif
			evt.stime=atoi(s[0].c_str());
			ifs>>evt.endstime>>evt.voice>>evt.eventtype>>evt.dur>>evt.numNotes;
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
		ofs<<"//HomVersion: 170101\n";
		for(int i=0;i<comments.size();i+=1){
			ofs<<"// "<<comments[i];
		}//endfor i
		for(int i=0;i<evts.size();i+=1){
			ofs<<evts[i].stime<<"\t"<<evts[i].endstime<<"\t"<<evts[i].voice<<"\t"<<evts[i].eventtype<<"\t"<<evts[i].dur<<"\t"<<evts[i].numNotes<<"\t";
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].notetypes[j]<<"\t";}//endfor j
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].sitches[j]<<"\t";}//endfor j
			for(int j=0;j<evts[i].numNotes;j+=1){ofs<<evts[i].fmt1IDs[j]<<"\t";}//endfor j
			ofs<<"\n";
		}//endfor i
		ofs.close();
	}//end WriteFile

	void ConvertFromFmt2(Fmt2 fmt2){
		comments.clear();
		evts.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		TPQN=fmt2.TPQN;
		vector<HomEvt> nevts;//For processing. Extended with endstime
		int NumOfVoices=0;
{
		HomEvt evt;
		for(int i=0;i<fmt2.evts.size();i+=1){
			evt.stime=fmt2.evts[i].stime;
			evt.voice=fmt2.evts[i].voice;
			evt.eventtype=fmt2.evts[i].eventtype;
			evt.dur=fmt2.evts[i].dur;
			evt.numNotes=fmt2.evts[i].numNotes;
			evt.notetypes=fmt2.evts[i].notetypes;
			evt.sitches=fmt2.evts[i].sitches;
			evt.fmt1IDs=fmt2.evts[i].fmt1IDs;
			nevts.push_back(evt);
			if(fmt2.evts[i].voice>NumOfVoices){NumOfVoices=fmt2.evts[i].voice;}
		}//endfor i
		//////////////////////EXTRA event for the homophonization stage
		evt.stime+=1;
		nevts.push_back(evt);
		//////////////////////EXTRA event for the homophonization stage
}//
		NumOfVoices+=1;

//// Check ordering
		for(int i=0;i<NumOfVoices;i+=1){
			int status=-1;//-1:nothing/rest, 0=after-note, 1=short-app, 2=chord/tremolo
			int prevStatus=-1;
			long curstime=-1;
			for(int m=0;m<nevts.size();m+=1){
				if(nevts[m].voice!=i){continue;}
				if(nevts[m].stime>curstime){curstime=nevts[m].stime; prevStatus=-1;status=-1;}
				if(nevts[m].eventtype=="after-note"){status=0;
				}else if(nevts[m].eventtype=="short-app"){status=1;
				}else if(nevts[m].eventtype=="chord"||nevts[m].eventtype=="tremolo"){status=2;
				}//endif
				if(status<prevStatus){
					cerr<<"Error in ordering at "<<m<<" "<<nevts[m].stime<<endl;
					assert(false);//???
				}//endif
				prevStatus=status;
			}//endfor m
		}//endfor i

////// Eliminating insertion of non-written after-notes before written ones
		for(int m=0;m<nevts.size();m+=1){
			if(nevts[m].eventtype=="chord"){
				for(int k=0;k<nevts[m].notetypes.size();k+=1){
					if(nevts[m].notetypes[k].find("Tr")!=string::npos){
						int Endstime=nevts[m].stime+nevts[m].dur;
						bool afternotesFound=false;
						for(int n=m+1;n<nevts.size();n+=1){
							if(nevts[n].stime>Endstime){break;}
							if(nevts[n].stime==Endstime&&nevts[n].eventtype=="after-note"
								&&nevts[n].voice==nevts[m].voice){
								afternotesFound=true; break;
							}//endif
						}//endfor n
						if(afternotesFound){
							s[0]=nevts[m].sitches[k];
							s[0]=s[0].substr(0,s[0].rfind(",")+1);
							nevts[m].sitches[k]=s[0];
						}//endif
					}//endif
				}//endfor k
			}//endif
		}//endfor m

		vector<int> preHomOnsets;
		preHomOnsets.push_back(0);
		for(int m=1;m<nevts.size();m+=1){
			if(nevts[m-1].stime!=nevts[m].stime){preHomOnsets.push_back(m);}
		}//endfor m
		preHomOnsets.push_back(preHomOnsets[preHomOnsets.size()-1]+nevts[nevts.size()-1].dur);

{
		HomEvt nevt;
		vector<HomEvt> trillObjects(NumOfVoices);
		nevt.stime=-1;
		for(int i=0;i<NumOfVoices;i+=1){trillObjects[i]=nevt;}
		int curHomPos=0;

		for(int m=0;m<nevts.size()-1;m+=1){

			if(m==preHomOnsets[curHomPos+1]){curHomPos+=1;}//endif
			for(int i=0;i<NumOfVoices;i+=1){
				if(trillObjects[i].stime<0){continue;}
				if(nevts[m].stime>trillObjects[i].stime&&nevts[m].stime<trillObjects[i].endstime&&nevts[m].voice>i){
					trillObjects[i].stime=nevts[m].stime;
					nevt=trillObjects[i];
					if(trillObjects[i].endstime>nevts[preHomOnsets[curHomPos+1]].stime){
						if(nevt.eventtype=="chord"){
							for(int k=0;k<nevt.sitches.size();k+=1){
								if(nevt.notetypes[k].find("Tr")!=string::npos){
									s[0]=nevt.sitches[k];
									s[0]=s[0].substr(0,s[0].rfind(",")+1);
									nevt.sitches[k]=s[0];
								}//endif
							}//endfor k
						}//endif
					}//endif
					evts.push_back(nevt);
					if(trillObjects[i].endstime>nevts[preHomOnsets[curHomPos+1]].stime){
						evts[evts.size()-1].endstime=nevts[preHomOnsets[curHomPos+1]].stime;
					}else{
						trillObjects[i].stime=-1;
					}//endif
				}//endif
			}//endfor i

			nevts[m].endstime=nevts[m].stime;
			bool containsAContinuedTrill=false;
			if(nevts[m].eventtype=="tremolo"){
				nevts[m].endstime=nevts[m].stime+nevts[m].dur;
				if(nevts[m].endstime>nevts[preHomOnsets[curHomPos+1]].stime){
					trillObjects[nevts[m].voice]=nevts[m];
				}//endif
			}else if(nevts[m].eventtype=="chord"){
				vector<int> trills;
				for(int k=0;k<nevts[m].notetypes.size();k+=1){
					if(nevts[m].notetypes[k].find("Tr")!=string::npos){trills.push_back(k);}
				}//endfor k
				if(trills.size()>0){
					nevts[m].endstime=nevts[m].stime+nevts[m].dur;
					if(nevts[m].endstime>nevts[preHomOnsets[curHomPos+1]].stime){
						containsAContinuedTrill=true;
						nevt=nevts[m];
						nevt.notetypes.clear();
						nevt.sitches.clear();
						nevt.fmt1IDs.clear();
						for(int k=0;k<trills.size();k+=1){
							nevt.notetypes.push_back(nevts[m].notetypes[trills[k]]);
							nevt.sitches.push_back(nevts[m].sitches[trills[k]]);
							nevt.fmt1IDs.push_back(nevts[m].fmt1IDs[trills[k]]);
						}//endfor k
						trillObjects[nevts[m].voice]=nevt;
					}//endif
				}//endif
			}//endif
			if(containsAContinuedTrill){
				nevt=nevts[m];
				for(int k=0;k<nevt.sitches.size();k+=1){
					if(nevt.notetypes[k].find("Tr")!=string::npos){
						s[0]=nevt.sitches[k];
						s[0]=s[0].substr(0,s[0].rfind(",")+1);
						nevt.sitches[k]=s[0];
					}//endif
				}//endfor k
				evts.push_back(nevt);
			}else{
				evts.push_back(nevts[m]);
			}//endif
			if(evts[evts.size()-1].endstime>nevts[preHomOnsets[curHomPos+1]].stime){
				evts[evts.size()-1].endstime=nevts[preHomOnsets[curHomPos+1]].stime;
			}//endif

		}//endfor m
}//

//// Check ordering
		for(int i=0;i<NumOfVoices;i+=1){
			int status=-1;//-1:nothing/rest, 0=after-note, 1=short-app, 2=chord/tremolo
			int prevStatus=-1;
			long curstime=-1;
			for(int m=0;m<evts.size();m+=1){
				if(evts[m].voice!=i){continue;}
				if(evts[m].stime>curstime){curstime=evts[m].stime; prevStatus=-1;status=-1;}
				if(evts[m].eventtype=="after-note"){status=0;
				}else if(evts[m].eventtype=="short-app"){status=1;
				}else if(evts[m].eventtype=="chord"||evts[m].eventtype=="tremolo"){status=2;
				}//endif
				if(status<prevStatus){cerr<<"Error in ordering at "<<m<<endl; assert(false);}
				prevStatus=status;
			}//endfor m
		}//endfor i



//// Eliminate redundancies
		vector<int> factorContent;//0=empty/rest, 1=pure trill, 2=otherwise
		preHomOnsets.clear();
		preHomOnsets.push_back(0);
{
		int content=2;
		for(int m=0;m<evts.size();m+=1){
			if(evts[m].eventtype=="rest"){evts.erase(evts.begin()+m);m-=1;}
		}//endfor m

		for(int m=1;m<evts.size();m+=1){
			if(evts[m-1].stime!=evts[m].stime){
				factorContent.push_back(content);
				preHomOnsets.push_back(m);
				content=0;
			}//endif
			if(evts[m].eventtype=="after-note"||evts[m].eventtype=="short-app"){
				content=2;
			}else if(content<1 && evts[m].eventtype.find("tremolo")!=string::npos){
				content=1;
			}else if(content<2 && evts[m].eventtype=="chord"){
				for(int k=0;k<evts[m].notetypes.size();k+=1){
					if(evts[m].notetypes[k].find("N")!=string::npos){content=2;}
					if(evts[m].notetypes[k].find("Tr")!=string::npos&&content<1){content=1;}
				}//endfor k
			}else{
			}//endif
		}//endfor m
		factorContent.push_back(content);
		preHomOnsets.push_back(evts.size());
		factorContent.push_back(2);

		for(int i=factorContent.size()-2;i>0;i-=1){
			if(factorContent[i]==0){
cerr<<"Error: there must be no rests here "<<preHomOnsets[i]<<endl;
				assert(false);
			}else if(factorContent[i]==1){
				bool included=true;
				if(i<=0){continue;}
				for(int j=preHomOnsets[i];j<preHomOnsets[i+1];j+=1){
					if(evts[j].eventtype!="chord" && evts[j].eventtype!="tremolo"){continue;}
					for(int k=0;k<evts[j].sitches.size();k+=1){
						bool found=false;
						for(int j2=preHomOnsets[i-1];j2<preHomOnsets[i];j2+=1){
							if(evts[j].eventtype!=evts[j2].eventtype){continue;}
							for(int k2=0;k2<evts[j].sitches.size();k2+=1){
								if(evts[j].notetypes[k]==evts[j2].notetypes[k2]&&evts[j].sitches[k]==evts[j2].sitches[k2]){
									found=true;
								}//endif
							}//endfor k2
						}//endfor j2
						if(!found){included=false;}
					}//endfor k
				}//endfor j
				if(included){
					long concatenate_endstime=evts[preHomOnsets[i]].stime;
					for(int j=preHomOnsets[i];j<preHomOnsets[i+1];j+=1){
						if(concatenate_endstime<evts[preHomOnsets[i]].endstime){concatenate_endstime=evts[preHomOnsets[i]].endstime;}
						evts.erase(evts.begin()+preHomOnsets[i]);
					}//endfor j
					for(int j=preHomOnsets[i-1];j<preHomOnsets[i];j+=1){
						if(evts[j].eventtype!="chord"){
							bool trilled=false;
							for(int k=0;k<evts[j].notetypes.size();k+=1){
								if(evts[j].notetypes[k].find("Tr")!=string::npos){trilled=true;break;}
							}//endfor k
							if(trilled){evts[j].endstime=concatenate_endstime;}
						}else if(evts[j].eventtype!="tremolo"){
							evts[j].endstime=concatenate_endstime;
						}//endif
					}//endfor j
				}//endif
			}//endif
		}//endfor i
}//

	for(int i=0;i<evts.size();i+=1){
		evts[i].numNotes=evts[i].notetypes.size();
	}//endfor i

	}//end ConvertFromFmt2

};//endclass Hom

#endif // Hom_HPP
