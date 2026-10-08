#ifndef Hmm_HPP
#define Hmm_HPP

#include<iostream>
#include<fstream>
#include<string>
#include<sstream>
#include<vector>
#include<stdio.h>
#include<cmath>
#include<cassert>
#include"Hom_v170104.hpp"
#include"Fmt3x_v170225.hpp"
#include"BasicPitchCalculation_v170101.hpp"

using namespace std;

class HmmEvt{
public:
	int stime;
	int endstime;
	int internalPosition;
	string stateType;//CH,SA,AN,TR
	int numClusters;
	int numSitches;
	int numCh;
	int numArp;
	int numInterCluster;//(Ncluster-1)
	//For CH/SA/AN: numSitches=numClusters+numCh+numArp, numInterCluster=numClusters-1
	//For TR: numSitches=numCh=numArp=numInterCluster=0
	vector<int> numNotesPerCluster;
	vector<vector<string> > sitchesPerCluster;
	vector<vector<int> > voicesPerCluster;
	vector<vector<string> > fmt1IDsPerCluster;
};//endclass HmmEvt

class DuplicateOnsetEvt{
public:
	int stime;
	string sitch;
	int numOnsets;
	vector<string> fmt1IDs;
};//endclass DuplicateOnsetEvt

class Hmm{
public:
	vector<string> comments;
	vector<HmmEvt> evts;
	vector<DuplicateOnsetEvt> duplicateOnsets;
	int TPQN;

	void Clear(){
		comments.clear();
		evts.clear();
		duplicateOnsets.clear();
	}//end Clear

	void ReadFile(string filename){
		comments.clear();
		evts.clear();
		duplicateOnsets.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;

		HmmEvt evt;
		ifstream ifs(filename.c_str());
		if(!ifs.is_open()){cout<<"File not found: "<<filename<<endl; assert(false);}
		while(ifs>>s[0]){
			if(s[0][0]=='/' || s[0][0]=='#'){
				if(s[0]=="//TPQN:"){
					ifs>>TPQN;
					getline(ifs,s[99]);
				}else if(s[0]=="//HmmVersion:"){
					ifs>>s[1];
					if(s[1]!="170101"){
						cout<<"Warning: The hmm version is not 170101!"<<endl;
					}//endif
					getline(ifs,s[99]);
				}else if(s[0]=="//DuplicateOnsets:"){
					DuplicateOnsetEvt dup;
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
			ifs>>evt.endstime>>evt.internalPosition>>evt.stateType>>evt.numClusters;
			ifs>>evt.numSitches>>evt.numCh>>evt.numArp>>evt.numInterCluster;
			evt.numNotesPerCluster.clear();
			for(int j=0;j<evt.numClusters;j+=1){ifs>>v[10]; evt.numNotesPerCluster.push_back(v[10]);}//endfor j
			evt.sitchesPerCluster.clear(); evt.sitchesPerCluster.resize(evt.numClusters);
			evt.voicesPerCluster.clear(); evt.voicesPerCluster.resize(evt.numClusters);
			evt.fmt1IDsPerCluster.clear(); evt.fmt1IDsPerCluster.resize(evt.numClusters);
			for(int j=0;j<evt.numClusters;j+=1)for(int k=0;k<evt.numNotesPerCluster[j];k+=1){
				ifs>>s[10]; evt.sitchesPerCluster[j].push_back(s[10]);
			}//endfor j,k
			for(int j=0;j<evt.numClusters;j+=1)for(int k=0;k<evt.numNotesPerCluster[j];k+=1){
				ifs>>v[10]; evt.voicesPerCluster[j].push_back(v[10]);
			}//endfor j,k
			for(int j=0;j<evt.numClusters;j+=1)for(int k=0;k<evt.numNotesPerCluster[j];k+=1){
				ifs>>s[10]; evt.fmt1IDsPerCluster[j].push_back(s[10]);
			}//endfor j,k
			getline(ifs,s[99]);
			evts.push_back(evt);
		}//endwhile
		ifs.close();
	}//end ReadFile

	void WriteFile(string filename){
		ofstream ofs(filename.c_str());
		ofs<<"//TPQN: "<<TPQN<<"\n";
		ofs<<"//HmmVersion: 170101\n";
		for(int i=0;i<duplicateOnsets.size();i+=1){
			ofs<<"//DuplicateOnsets: "<<duplicateOnsets[i].stime<<"\t"<<duplicateOnsets[i].sitch<<"\t"<<duplicateOnsets[i].numOnsets<<"\t";
			for(int j=0;j<duplicateOnsets[i].numOnsets;j+=1){
				ofs<<duplicateOnsets[i].fmt1IDs[j]<<"\t";
			}//endfor j
			ofs<<"\n";
		}//endfor i
		for(int i=0;i<comments.size();i+=1){
			ofs<<"// "<<comments[i];
		}//endfor i
		for(int i=0;i<evts.size();i+=1){
			ofs<<evts[i].stime<<"\t"<<evts[i].endstime<<"\t"<<evts[i].internalPosition<<"\t"<<evts[i].stateType<<"\t"<<evts[i].numClusters<<"\t";
			ofs<<evts[i].numSitches<<"\t"<<evts[i].numCh<<"\t"<<evts[i].numArp<<"\t"<<evts[i].numInterCluster<<"\t";
			for(int j=0;j<evts[i].numClusters;j+=1){
				ofs<<evts[i].numNotesPerCluster[j]<<"\t";
			}//endfor j
			for(int j=0;j<evts[i].numClusters;j+=1)for(int k=0;k<evts[i].numNotesPerCluster[j];k+=1){
				ofs<<evts[i].sitchesPerCluster[j][k]<<"\t";
			}//endfor j,k
			for(int j=0;j<evts[i].numClusters;j+=1)for(int k=0;k<evts[i].numNotesPerCluster[j];k+=1){
				ofs<<evts[i].voicesPerCluster[j][k]<<"\t";
			}//endfor j,k
			for(int j=0;j<evts[i].numClusters;j+=1)for(int k=0;k<evts[i].numNotesPerCluster[j];k+=1){
				ofs<<evts[i].fmt1IDsPerCluster[j][k]<<"\t";
			}//endfor j,k
			ofs<<"\n";
		}//endfor i
		ofs.close();
	}//end WriteFile

	void ConvertFromHom(Hom hom){
		comments.clear();
		evts.clear();
		duplicateOnsets.clear();
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		stringstream ss;
		TPQN=hom.TPQN;
		HmmEvt hmmevt;

		int NumOfVoices=0;
		for(int i=0;i<hom.evts.size();i+=1){
			if(hom.evts[i].voice>NumOfVoices){NumOfVoices=hom.evts[i].voice;}
		}//endfor i
		NumOfVoices+=1;

//// Check ordering
		for(int i=0;i<NumOfVoices;i+=1){
			int status=-1;//-1:nothing/rest, 0=after-note, 1=short-app, 2=chord/tremolo
			int prevStatus=-1;
			int curstime=-1;
			for(int m=0;m<hom.evts.size();m+=1){
				if(hom.evts[m].voice!=i){continue;}
				if(hom.evts[m].stime>curstime){curstime=hom.evts[m].stime; prevStatus=-1;status=-1;}
				if(hom.evts[m].eventtype=="after-note"){status=0;
				}else if(hom.evts[m].eventtype=="short-app"){status=1;
				}else if(hom.evts[m].eventtype=="chord"||hom.evts[m].eventtype=="tremolo"){status=2;
				}//endif
				if(status<prevStatus){cout<<"Error in ordering at "<<m<<endl; assert(false);}
				prevStatus=status;
			}//endfor m
		}//endfor i

// cerr<<"&&&&&&&&&&&&&&& 2"<<endl;

{
		int curStime=-1;
		int curType=0;//0=after-note, 1=short-app, 2=chord, 3=tremolo
		int preType;
		vector<HomEvt> nevts_an,nevts_sa,nevts_ch,nevts_tm;
		vector<vector<HomEvt> > reorderedNevts(NumOfVoices);
		vector<string> ditches,refs;
		vector<int> voices;
		int Nch,Narp,Nsa,preVoice,Ncluster,NrelevantVoice;

		for(int i=0;i<hom.evts.size()+1;i+=1){
//cerr<<i<<" "<<curStime<<endl;
			if(i<hom.evts.size()){
			if(hom.evts[i].stime==curStime){
				if(hom.evts[i].eventtype=="after-note"){nevts_an.push_back(hom.evts[i]); curType=0;
				}else if(hom.evts[i].eventtype=="short-app"){nevts_sa.push_back(hom.evts[i]); curType=1;
				}else if(hom.evts[i].eventtype=="chord"){nevts_ch.push_back(hom.evts[i]); curType=2;
				}else if(hom.evts[i].eventtype=="tremolo"){nevts_tm.push_back(hom.evts[i]); curType=3;
				}//endif
				curStime=hom.evts[i].stime;
				continue;
			}//endif
			}//endif

			int internalPosition=1;

//if(curStime==6352){cerr<<nevts_an.size()<<endl;}

			if(nevts_an.size()>0){

				Nch=0;Nsa=0;Narp=0;
				bool multiRef=false;
				for(int m=0;m<NumOfVoices;m+=1){reorderedNevts[m].clear();}//endfor m
				for(int j=0;j<nevts_an.size();j+=1){
					reorderedNevts[nevts_an[j].voice].push_back(nevts_an[j]);
					for(int k=0;k<nevts_an[j].fmt1IDs.size();k+=1){
						if(nevts_an[0].fmt1IDs[0]!=nevts_an[j].fmt1IDs[k]){multiRef=true;}
					}//endfor k
				}//endfor j
				Ncluster=0;
				NrelevantVoice=0;
				for(int m=0;m<NumOfVoices;m+=1){
					if(reorderedNevts[m].size()>Ncluster){Ncluster=reorderedNevts[m].size();}
					if(reorderedNevts[m].size()>0){NrelevantVoice+=1;}
				}//endfor m

				if(NrelevantVoice==1&&multiRef){
					int relevantVoice;
					for(int m=0;m<NumOfVoices;m+=1){
						if(reorderedNevts[m].size()>0){relevantVoice=m;}
					}//endfor m
					for(int c=0;c<Ncluster;c+=1){
						Nch=0;
						Narp=0;
						for(int k=1;k<reorderedNevts[relevantVoice][c].notetypes.size();k+=1){
							if(reorderedNevts[relevantVoice][c].notetypes[k].find("Arp")==string::npos){Nch+=1;
							}else{Narp+=1;
							}//endif
						}//endfor k
						assert(Nch+Narp+1==reorderedNevts[relevantVoice][c].sitches.size());

						hmmevt.stime            =nevts_an[0].stime;
						hmmevt.endstime         =nevts_an[0].stime;
						hmmevt.internalPosition =internalPosition;
						hmmevt.stateType        ="AN";
						hmmevt.numClusters      =1;
						hmmevt.numSitches       =reorderedNevts[relevantVoice][c].sitches.size();
						hmmevt.numCh            =Nch;
						hmmevt.numArp           =Narp;
						hmmevt.numInterCluster  =0;
						hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
						hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
						hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
						hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
						hmmevt.numNotesPerCluster[0]=reorderedNevts[relevantVoice][c].sitches.size();
						for(int k=0;k<reorderedNevts[relevantVoice][c].sitches.size();k+=1){
							hmmevt.sitchesPerCluster[0].push_back(reorderedNevts[relevantVoice][c].sitches[k]);
							hmmevt.voicesPerCluster[0].push_back(reorderedNevts[relevantVoice][c].voice);
							hmmevt.fmt1IDsPerCluster[0].push_back(reorderedNevts[relevantVoice][c].fmt1IDs[k]);
						}//endfor k
						evts.push_back(hmmevt);

						internalPosition+=1;
					}//endfor c
				}else{//NrelevantVoice > 1
					vector<vector<string> > ditches_clusters,refs_clusters;
					vector<vector<int> > voices_clusters;
					for(int c=0;c<Ncluster;c+=1){
						ditches.clear();
						refs.clear();
						voices.clear();
						Nch-=1;
						for(int m=0;m<NumOfVoices;m+=1){
							if(reorderedNevts[m].size()<=c){continue;}//endif
							for(int k=0;k<reorderedNevts[m][c].notetypes.size();k+=1){
								ditches.push_back(reorderedNevts[m][c].sitches[k]);
								refs.push_back(reorderedNevts[m][c].fmt1IDs[k]);
								voices.push_back(reorderedNevts[m][c].voice);
							}//endfor k
							Nch+=1;
							for(int k=1;k<reorderedNevts[m][c].notetypes.size();k+=1){
								if(reorderedNevts[m][c].notetypes[k].find("Arp")==string::npos){Nch+=1;
								}else{Narp+=1;
								}//endif
							}//endfor k
						}//endfor m
						ditches_clusters.push_back(ditches);
						refs_clusters.push_back(refs);
						voices_clusters.push_back(voices);
					}//endfor c

					hmmevt.stime            =nevts_an[0].stime;
					hmmevt.endstime         =nevts_an[0].stime;
					hmmevt.internalPosition =internalPosition;
					hmmevt.stateType        ="AN";
					hmmevt.numClusters      =Ncluster;
					hmmevt.numSitches       =Nch+Narp+Ncluster;
					hmmevt.numCh            =Nch;
					hmmevt.numArp           =Narp;
					hmmevt.numInterCluster  =Ncluster-1;
					hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
					hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
					hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
					hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
					for(int c=0;c<Ncluster;c+=1){
						hmmevt.numNotesPerCluster[c]=ditches_clusters[c].size();
						for(int k=0;k<ditches_clusters[c].size();k+=1){
							hmmevt.sitchesPerCluster[c].push_back(ditches_clusters[c][k]);
							hmmevt.voicesPerCluster[c].push_back(voices_clusters[c][k]);
							hmmevt.fmt1IDsPerCluster[c].push_back(refs_clusters[c][k]);
						}//endfor k
					}//endfor c
					evts.push_back(hmmevt);

					internalPosition+=1;
				}//endif about NrelevantVoice

			}//endif


			int chordalAndTrill=0;//1=no trill/tremolo, 2=pure trill/tremolo, 3=trill/tremolo w/ chord
			if(nevts_sa.size()>0){chordalAndTrill+=1;}//endif
			if(nevts_ch.size()>0){
				for(int j=0;j<nevts_ch.size();j+=1){
					for(int k=0;k<nevts_ch[j].notetypes.size();k+=1){
						if(nevts_ch[j].notetypes[k].find("Tr")!=string::npos){
							if(chordalAndTrill<2){chordalAndTrill+=2;}
						}else{
							if(chordalAndTrill%2==0){chordalAndTrill+=1;}
						}//endif
					}//endfor k
				}//endfor j
			}//endif
			if(nevts_tm.size()>0&&chordalAndTrill<2){chordalAndTrill+=2;}//endif

// if(curStime==1360){cerr<<"chordalAndTrill "<<chordalAndTrill<<endl;}

			if(chordalAndTrill==1){//purely chordal

				if(nevts_sa.size()+nevts_ch.size()>0){

//if(curStime==6352){cerr<<"chordalAndTrill "<<chordalAndTrill<<" "<<reorderedNevts.size()<<" "<<NumOfVoices<<endl;}

					bool multiRef=false;

					Nch=0;Nsa=0;Narp=0;
					int stime;
					for(int m=0;m<NumOfVoices;m+=1){reorderedNevts[m].clear();}//endfor m
					for(int j=nevts_sa.size()-1;j>=0;j-=1){
						if(nevts_sa[j].sitches.size()==0){nevts_sa.erase(nevts_sa.begin()+j);}
					}//endfor j

					string firstFmt1ID="";
					for(int j=0;j<nevts_sa.size();j+=1){
						if(nevts_sa[j].sitches.size()==0){continue;}
						if(firstFmt1ID==""){firstFmt1ID=nevts_sa[j].fmt1IDs[0];}
						stime=nevts_sa[j].stime;
						reorderedNevts[nevts_sa[j].voice].push_back(nevts_sa[j]);
						if(nevts_sa.size()>0){
							for(int k=0;k<nevts_sa[j].fmt1IDs.size();k+=1){
								if(firstFmt1ID!=nevts_sa[j].fmt1IDs[k]){multiRef=true;}
							}//endfor k
						}//endif
					}//endfor j
					for(int j=0;j<nevts_ch.size();j+=1){
						stime=nevts_ch[j].stime;
						reorderedNevts[nevts_ch[j].voice].push_back(nevts_ch[j]);
					}//endfor j
					Ncluster=0;
					NrelevantVoice=0;
					for(int m=0;m<NumOfVoices;m+=1){
						if(reorderedNevts[m].size()>Ncluster){Ncluster=reorderedNevts[m].size();};
						if(reorderedNevts[m].size()>0){NrelevantVoice+=1;}
					}//endfor m

// if(curStime==1360){cerr<<"NrelevantVoice "<<NrelevantVoice<<endl;}

					if(NrelevantVoice==1&&nevts_sa.size()>0&&multiRef){

						for(int c=0;c<nevts_sa.size();c+=1){
							Nch=0;Narp=0;
							for(int k=1;k<nevts_sa[c].sitches.size();k+=1){
								if(nevts_sa[c].notetypes[k].find("Arp")==string::npos){Nch+=1;
								}else{Narp+=1;
								}//endif
							}//endfor k
							assert(Nch+Narp+1==nevts_sa[c].sitches.size());

							hmmevt.stime            =nevts_sa[c].stime;
							hmmevt.endstime         =nevts_sa[c].stime;
							hmmevt.internalPosition =internalPosition;
							hmmevt.stateType        ="SA";
							hmmevt.numClusters      =1;
							hmmevt.numSitches       =nevts_sa[c].sitches.size();
							hmmevt.numCh            =Nch;
							hmmevt.numArp           =Narp;
							hmmevt.numInterCluster  =0;
							hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
							hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
							hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
							hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
							hmmevt.numNotesPerCluster[0]=nevts_sa[c].sitches.size();
							for(int k=0;k<nevts_sa[c].sitches.size();k+=1){
								hmmevt.sitchesPerCluster[0].push_back(nevts_sa[c].sitches[k]);
								hmmevt.voicesPerCluster[0].push_back(nevts_sa[c].voice);
								hmmevt.fmt1IDsPerCluster[0].push_back(nevts_sa[c].fmt1IDs[k]);
							}//endfor k
							evts.push_back(hmmevt);
							internalPosition+=1;
						}//endfor c
						assert(nevts_ch.size()==1);

						Nch=0;Narp=0;
						for(int k=1;k<nevts_ch[0].sitches.size();k+=1){
							if(nevts_ch[0].notetypes[k].find("Arp")==string::npos){Nch+=1;
							}else{Narp+=1;
							}//endif
						}//endfor k
						assert(Nch+Narp+1==nevts_ch[0].sitches.size());

						hmmevt.stime            =nevts_ch[0].stime;
						hmmevt.endstime         =nevts_ch[0].stime;
						hmmevt.internalPosition =internalPosition;
						hmmevt.stateType        ="CH";
						hmmevt.numClusters      =1;
						hmmevt.numSitches       =nevts_ch[0].sitches.size();
						hmmevt.numCh            =Nch;
						hmmevt.numArp           =Narp;
						hmmevt.numInterCluster  =0;
						hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
						hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
						hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
						hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
						hmmevt.numNotesPerCluster[0]=nevts_ch[0].sitches.size();
						for(int k=0;k<nevts_ch[0].sitches.size();k+=1){
							hmmevt.sitchesPerCluster[0].push_back(nevts_ch[0].sitches[k]);
							hmmevt.voicesPerCluster[0].push_back(nevts_ch[0].voice);
							hmmevt.fmt1IDsPerCluster[0].push_back(nevts_ch[0].fmt1IDs[k]);
						}//endfor k
						evts.push_back(hmmevt);
						internalPosition+=1;

					}else{//if NrelevantVoice > 1 or purely chordal

						vector<vector<string> > ditches_clusters,refs_clusters;
						vector<vector<int> > voices_clusters;
						for(int c=0;c<Ncluster;c+=1){
							ditches.clear();
							refs.clear();
							voices.clear();
							Nch-=1;
							for(int m=0;m<NumOfVoices;m+=1){
								if(reorderedNevts[m].size()<=c){continue;}//endif
								for(int k=0;k<reorderedNevts[m][c].notetypes.size();k+=1){
									ditches.push_back(reorderedNevts[m][c].sitches[k]);
									refs.push_back(reorderedNevts[m][c].fmt1IDs[k]);
									voices.push_back(reorderedNevts[m][c].voice);
								}//endfor k
								Nch+=1;
								for(int k=1;k<reorderedNevts[m][c].notetypes.size();k+=1){
									if(reorderedNevts[m][c].notetypes[k].find("Arp")==string::npos){Nch+=1;
									}else{Narp+=1;
									}//endif
								}//endfor k
							}//endfor m
							ditches_clusters.push_back(ditches);
							refs_clusters.push_back(refs);
							voices_clusters.push_back(voices);
						}//endfor c

						hmmevt.stime            =stime;
						hmmevt.endstime         =stime;
						hmmevt.internalPosition =internalPosition;
						hmmevt.stateType        ="CH";
						hmmevt.numClusters      =Ncluster;
						hmmevt.numSitches       =Nch+Narp+Ncluster;
						hmmevt.numCh            =Nch;
						hmmevt.numArp           =Narp;
						hmmevt.numInterCluster  =Ncluster-1;
						hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
						hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
						hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
						hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
						for(int c=0;c<Ncluster;c+=1){
							hmmevt.numNotesPerCluster[c]=ditches_clusters[c].size();
							for(int k=0;k<ditches_clusters[c].size();k+=1){
								hmmevt.sitchesPerCluster[c].push_back(ditches_clusters[c][k]);
								hmmevt.voicesPerCluster[c].push_back(voices_clusters[c][k]);
								hmmevt.fmt1IDsPerCluster[c].push_back(refs_clusters[c][k]);
							}//endfor k
						}//endfor c
						evts.push_back(hmmevt);
						internalPosition+=1;

					}//endif

				}//endif

			}else if(chordalAndTrill==2){//purely trill/tremolo

				vector<string> anCluster,anRef;
				vector<vector<string> > trCluster(2),trRef(2);
				vector<int> anVoice;
				vector<vector<int> > trVoice(2);
				int stime,endstime=0;
				for(int j=0;j<nevts_ch.size();j+=1){
					for(int k=0;k<nevts_ch[j].notetypes.size();k+=1){
						if(nevts_ch[j].notetypes[k].find("Tr")==string::npos){continue;}
						stime=nevts_ch[j].stime;
						if(nevts_ch[j].endstime>endstime){endstime=nevts_ch[j].endstime;}
						s[0]=nevts_ch[j].sitches[k];
						trCluster[0].push_back(s[0].substr(0,s[0].find(",")));
						trRef[0].push_back(nevts_ch[j].fmt1IDs[k]);
						trVoice[0].push_back(nevts_ch[j].voice);
						s[0]=s[0].substr(s[0].find(",")+1,s[0].size());
						trCluster[1].push_back(s[0].substr(0,s[0].find(",")));
						trRef[1].push_back(nevts_ch[j].fmt1IDs[k]);
						trVoice[1].push_back(nevts_ch[j].voice);
						s[0]=s[0].substr(s[0].find(",")+1,s[0].size());
						if(s[0].find_first_of("ABCDEFG")!=string::npos){
							anCluster.push_back(s[0]);
							anRef.push_back(nevts_ch[j].fmt1IDs[k]);
							anVoice.push_back(nevts_ch[j].voice);
						}//endif
					}//endfor k
				}//endfor j
				for(int j=0;j<nevts_tm.size();j+=1){
					stime=nevts_tm[j].stime;
					if(nevts_tm[j].endstime>endstime){endstime=nevts_tm[j].endstime;}
					for(int k=0;k<nevts_tm[j].notetypes.size();k+=1){
						v[0]=atoi((nevts_tm[j].notetypes[k]).c_str());
						if(k>=trCluster.size()){
							vector<string> vs;
							trCluster.push_back(vs);
							trRef.push_back(vs);
							vector<int> vi;
							trVoice.push_back(vi);
						}//endif
						s[0]=nevts_tm[j].sitches[k];
						s[1]=nevts_tm[j].fmt1IDs[k];
						for(int l=0;l<v[0];l+=1){
							trCluster[k].push_back(s[0].substr(0,s[0].find(",")));
							trRef[k].push_back(s[1].substr(0,s[1].find(",")));
							trVoice[k].push_back(nevts_tm[j].voice);
							s[0]=s[0].substr(s[0].find(",")+1,s[0].size());
							s[1]=s[1].substr(s[1].find(",")+1,s[1].size());
						}//endfor l
					}//endfor k
				}//endfor j

				hmmevt.stime            =stime;
				hmmevt.endstime         =endstime;
				hmmevt.internalPosition =internalPosition;
				hmmevt.stateType        ="TR";
				hmmevt.numClusters      =trCluster.size()+1;
				hmmevt.numSitches       =0;
				hmmevt.numCh            =0;
				hmmevt.numArp           =0;
				hmmevt.numInterCluster  =0;
				hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
				hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
				hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
				hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
				for(int c=0;c<trCluster.size();c+=1){
					hmmevt.numNotesPerCluster[c]=trCluster[c].size();
					for(int k=0;k<trCluster[c].size();k+=1){
						hmmevt.sitchesPerCluster[c].push_back(trCluster[c][k]);
						hmmevt.voicesPerCluster[c].push_back(trVoice[c][k]);
						hmmevt.fmt1IDsPerCluster[c].push_back(trRef[c][k]);
					}//endfor k
				}//endfor c
				hmmevt.numNotesPerCluster[hmmevt.numClusters-1]=anCluster.size();
				for(int k=0;k<anCluster.size();k+=1){
					hmmevt.sitchesPerCluster[hmmevt.numClusters-1].push_back(anCluster[k]);
					hmmevt.voicesPerCluster[hmmevt.numClusters-1].push_back(anVoice[k]);
					hmmevt.fmt1IDsPerCluster[hmmevt.numClusters-1].push_back(anRef[k]);
				}//endfor k
				evts.push_back(hmmevt);
				internalPosition+=1;

			}else if(chordalAndTrill==3){//chord + trill/tremolo

				Nch=0;Nsa=0;Narp=0;
				long stime,endstime=0;
				for(int m=0;m<NumOfVoices;m+=1){reorderedNevts[m].clear();}//endfor m
				for(int j=0;j<nevts_sa.size();j+=1){
					stime=nevts_sa[j].stime;
					reorderedNevts[nevts_sa[j].voice].push_back(nevts_sa[j]);
				}//endfor j
				for(int j=0;j<nevts_ch.size();j+=1){
					bool withChordal=false;
					for(int k=0;k<nevts_ch[j].notetypes.size();k+=1){
						if(nevts_ch[j].notetypes[k].find("N")!=string::npos){withChordal=true;}
					}//endfor k
					if(withChordal){
						stime=nevts_ch[j].stime;
						reorderedNevts[nevts_ch[j].voice].push_back(nevts_ch[j]);
					}//endif
				}//endfor j

				Ncluster=0;
				NrelevantVoice=0;
				for(int m=0;m<NumOfVoices;m+=1){
					if(reorderedNevts[m].size()>Ncluster){Ncluster=reorderedNevts[m].size();};
					if(reorderedNevts[m].size()>0){NrelevantVoice+=1;}
				}//endfor m

// if(curStime==1360){cerr<<"NrelevantVoice "<<NrelevantVoice<<endl;}

				if(NrelevantVoice==1&&nevts_sa.size()>0){

					for(int c=0;c<nevts_sa.size();c+=1){
						Nch=0;Narp=0;
						for(int k=1;k<nevts_sa[c].sitches.size();k+=1){
							if(nevts_sa[c].notetypes[k].find("Arp")==string::npos){Nch+=1;
							}else{Narp+=1;
							}//endif
						}//endfor k
						assert(Nch+Narp+1==nevts_sa[c].sitches.size());

						hmmevt.stime            =nevts_sa[c].stime;
						hmmevt.endstime         =nevts_sa[c].stime;
						hmmevt.internalPosition =internalPosition;
						hmmevt.stateType        ="SA";
						hmmevt.numClusters      =1;
						hmmevt.numSitches       =nevts_sa[c].sitches.size();
						hmmevt.numCh            =Nch;
						hmmevt.numArp           =Narp;
						hmmevt.numInterCluster  =0;
						hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
						hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
						hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
						hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
						hmmevt.numNotesPerCluster[0]=nevts_sa[c].sitches.size();
						for(int k=0;k<nevts_sa[c].sitches.size();k+=1){
							hmmevt.sitchesPerCluster[0].push_back(nevts_sa[c].sitches[k]);
							hmmevt.voicesPerCluster[0].push_back(nevts_sa[c].voice);
							hmmevt.fmt1IDsPerCluster[0].push_back(nevts_sa[c].fmt1IDs[k]);
						}//endfor k
						evts.push_back(hmmevt);
						internalPosition+=1;
					}//endfor c

					for(int j=0;j<nevts_ch.size();j+=1){
						bool isTr=false;
						for(int k=0;k<nevts_ch[j].notetypes.size();k+=1){
							if(nevts_ch[j].notetypes[k].find("Tr")!=string::npos){isTr=true; break;}
						}//endfor k
						if(isTr){continue;}

						Nch=0;Narp=0;
						for(int k=1;k<nevts_ch[j].sitches.size();k+=1){
							if(nevts_ch[j].notetypes[k].find("Arp")==string::npos){Nch+=1;
							}else{Narp+=1;
							}//endif
						}//endfor k

						assert(Nch+Narp+1==nevts_ch[j].sitches.size());
	
						hmmevt.stime            =nevts_ch[j].stime;
						hmmevt.endstime         =nevts_ch[j].stime;
						hmmevt.internalPosition =internalPosition;
						hmmevt.stateType        ="CH";
						hmmevt.numClusters      =1;
						hmmevt.numSitches       =nevts_ch[j].sitches.size();
						hmmevt.numCh            =Nch;
						hmmevt.numArp           =Narp;
						hmmevt.numInterCluster  =0;
						hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
						hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
						hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
						hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
						hmmevt.numNotesPerCluster[0]=nevts_ch[j].sitches.size();
						for(int k=0;k<nevts_ch[j].sitches.size();k+=1){
							hmmevt.sitchesPerCluster[0].push_back(nevts_ch[j].sitches[k]);
							hmmevt.voicesPerCluster[0].push_back(nevts_ch[j].voice);
							hmmevt.fmt1IDsPerCluster[0].push_back(nevts_ch[j].fmt1IDs[k]);
						}//endfor k
						evts.push_back(hmmevt);
						internalPosition+=1;

					}//endfor j

//************************** replaced 22/1/27
// 					if(nevts_ch.size()!=1){
// cerr<<"Err: "<<curStime<<" "<<nevts_ch.size()<<endl; assert(false);
// 					}//endif
// 
// 					Nch=0;Narp=0;
// 					for(int k=1;k<nevts_ch[0].sitches.size();k+=1){
// 						if(nevts_ch[0].notetypes[k].find("Arp")==string::npos){Nch+=1;
// 						}else{Narp+=1;
// 						}//endif
// 					}//endfor k
// 
// 					assert(Nch+Narp+1==nevts_ch[0].sitches.size());
// 
// 					hmmevt.stime            =nevts_ch[0].stime;
// 					hmmevt.endstime         =nevts_ch[0].stime;
// 					hmmevt.internalPosition =internalPosition;
// 					hmmevt.stateType        ="CH";
// 					hmmevt.numClusters      =1;
// 					hmmevt.numSitches       =nevts_ch[0].sitches.size();
// 					hmmevt.numCh            =Nch;
// 					hmmevt.numArp           =Narp;
// 					hmmevt.numInterCluster  =0;
// 					hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
// 					hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
// 					hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
// 					hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
// 					hmmevt.numNotesPerCluster[0]=nevts_ch[0].sitches.size();
// 					for(int k=0;k<nevts_ch[0].sitches.size();k+=1){
// 						hmmevt.sitchesPerCluster[0].push_back(nevts_ch[0].sitches[k]);
// 						hmmevt.voicesPerCluster[0].push_back(nevts_ch[0].voice);
// 						hmmevt.fmt1IDsPerCluster[0].push_back(nevts_ch[0].fmt1IDs[k]);
// 					}//endfor k
// // 					evts.push_back(hmmevt);
// // 					internalPosition+=1;
// //->???
//************************** replaced 22/1/27

				}else{//if NrelevantVoice > 1 or purely chordal

					vector<vector<string> > ditches_clusters,refs_clusters;
					vector<vector<int> > voices_clusters;
					for(int c=0;c<Ncluster;c+=1){
						ditches.clear();
						refs.clear();
						voices.clear();
						Nch-=1;
						for(int m=0;m<NumOfVoices;m+=1){
							if(reorderedNevts[m].size()<=c){continue;}//endif
							for(int k=0;k<reorderedNevts[m][c].notetypes.size();k+=1){
								if(reorderedNevts[m][c].notetypes[k].find("Tr")!=string::npos){continue;}
								ditches.push_back(reorderedNevts[m][c].sitches[k]);
								refs.push_back(reorderedNevts[m][c].fmt1IDs[k]);
								voices.push_back(reorderedNevts[m][c].voice);
							}//endfor k
							Nch+=1;
							for(int k=1;k<reorderedNevts[m][c].notetypes.size();k+=1){
								if(reorderedNevts[m][c].notetypes[k].find("Tr")!=string::npos){continue;}
								if(reorderedNevts[m][c].notetypes[k].find("Arp")==string::npos){Nch+=1;
								}else{Narp+=1;
								}//endif
							}//endfor k
						}//endfor m
						ditches_clusters.push_back(ditches);
						refs_clusters.push_back(refs);
						voices_clusters.push_back(voices);
					}//endfor c

					hmmevt.stime            =stime;
					hmmevt.endstime         =stime;
					hmmevt.internalPosition =internalPosition;
					hmmevt.stateType        ="SA";
					hmmevt.numClusters      =Ncluster;
					hmmevt.numSitches       =Nch+Narp+Ncluster;
					hmmevt.numCh            =Nch;
					hmmevt.numArp           =Narp;
					hmmevt.numInterCluster  =Ncluster-1;
					hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
					hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
					hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
					hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
					for(int c=0;c<Ncluster;c+=1){
						hmmevt.numNotesPerCluster[c]=ditches_clusters[c].size();
						for(int k=0;k<ditches_clusters[c].size();k+=1){
							hmmevt.sitchesPerCluster[c].push_back(ditches_clusters[c][k]);
							hmmevt.voicesPerCluster[c].push_back(voices_clusters[c][k]);
							hmmevt.fmt1IDsPerCluster[c].push_back(refs_clusters[c][k]);
						}//endfor k
					}//endfor c
					evts.push_back(hmmevt);
					internalPosition+=1;
				}//endif about NrelevantVoice
	//////////////////////////////////////////////////////////
				vector<string> anCluster,anRef;
				vector<vector<string> > trCluster(2),trRef(2);
				vector<int> anVoice;
				vector<vector<int> > trVoice(2);
				for(int j=0;j<nevts_ch.size();j+=1){
					for(int k=0;k<nevts_ch[j].notetypes.size();k+=1){
						if(nevts_ch[j].notetypes[k].find("Tr")!=string::npos){
							stime=nevts_ch[j].stime;
							if(nevts_ch[j].endstime>endstime){endstime=nevts_ch[j].endstime;}
							s[0]=nevts_ch[j].sitches[k];
							trCluster[0].push_back(s[0].substr(0,s[0].find(",")));
							trRef[0].push_back(nevts_ch[j].fmt1IDs[k]);
							trVoice[0].push_back(nevts_ch[j].voice);
							s[0]=s[0].substr(s[0].find(",")+1,s[0].size());
							trCluster[1].push_back(s[0].substr(0,s[0].find(",")));
							trRef[1].push_back(nevts_ch[j].fmt1IDs[k]);
							trVoice[1].push_back(nevts_ch[j].voice);
							s[0]=s[0].substr(s[0].find(",")+1,s[0].size());
							if(s[0].find_first_of("ABCDEFG")!=string::npos){
								anCluster.push_back(s[0]);
								anRef.push_back(nevts_ch[j].fmt1IDs[k]);
								anVoice.push_back(nevts_ch[j].voice);
							}//endif
						}//endif
					}//endfor k
				}//endfor j
				for(int j=0;j<nevts_tm.size();j+=1){
					stime=nevts_tm[j].stime;
					if(nevts_tm[j].endstime>endstime){endstime=nevts_tm[j].endstime;}
					for(int k=0;k<nevts_tm[j].notetypes.size();k+=1){
						v[0]=atoi((nevts_tm[j].notetypes[k]).c_str());
						if(k>=trCluster.size()){
							vector<string> vs;
							trCluster.push_back(vs);
							trRef.push_back(vs);
							vector<int> vi;
							trVoice.push_back(vi);
						}//endif
						s[0]=nevts_tm[j].sitches[k];
						s[1]=nevts_tm[j].fmt1IDs[k];
						for(int l=0;l<v[0];l+=1){
							trCluster[k].push_back(s[0].substr(0,s[0].find(",")));
							trRef[k].push_back(s[1].substr(0,s[1].find(",")));
							trVoice[k].push_back(nevts_tm[j].voice);
							s[0]=s[0].substr(s[0].find(",")+1,s[0].size());
							s[1]=s[1].substr(s[1].find(",")+1,s[1].size());
						}//endfor l
					}//endfor k
				}//endfor j

				hmmevt.stime            =stime;
				hmmevt.endstime         =endstime;
				hmmevt.internalPosition =internalPosition;
				hmmevt.stateType        ="TR";
				hmmevt.numClusters      =trCluster.size()+1;
				hmmevt.numSitches       =0;
				hmmevt.numCh            =0;
				hmmevt.numArp           =0;
				hmmevt.numInterCluster  =0;
				hmmevt.numNotesPerCluster.clear(); hmmevt.numNotesPerCluster.resize(hmmevt.numClusters);
				hmmevt.sitchesPerCluster.clear(); hmmevt.sitchesPerCluster.resize(hmmevt.numClusters);
				hmmevt.voicesPerCluster.clear(); hmmevt.voicesPerCluster.resize(hmmevt.numClusters);
				hmmevt.fmt1IDsPerCluster.clear(); hmmevt.fmt1IDsPerCluster.resize(hmmevt.numClusters);
				for(int c=0;c<trCluster.size();c+=1){
					hmmevt.numNotesPerCluster[c]=trCluster[c].size();
					for(int k=0;k<trCluster[c].size();k+=1){
						hmmevt.sitchesPerCluster[c].push_back(trCluster[c][k]);
						hmmevt.voicesPerCluster[c].push_back(trVoice[c][k]);
						hmmevt.fmt1IDsPerCluster[c].push_back(trRef[c][k]);
					}//endfor k
				}//endfor c
				hmmevt.numNotesPerCluster[hmmevt.numClusters-1]=anCluster.size();
				for(int k=0;k<anCluster.size();k+=1){
					hmmevt.sitchesPerCluster[hmmevt.numClusters-1].push_back(anCluster[k]);
					hmmevt.voicesPerCluster[hmmevt.numClusters-1].push_back(anVoice[k]);
					hmmevt.fmt1IDsPerCluster[hmmevt.numClusters-1].push_back(anRef[k]);
				}//endfor k
				evts.push_back(hmmevt);
				internalPosition+=1;

			}//endif

			nevts_an.clear();
			nevts_sa.clear();
			nevts_ch.clear();
			nevts_tm.clear();

			if(i<hom.evts.size()){
				if(hom.evts[i].eventtype=="after-note"){nevts_an.push_back(hom.evts[i]); curType=0;
				}else if(hom.evts[i].eventtype=="short-app"){nevts_sa.push_back(hom.evts[i]); curType=1;
				}else if(hom.evts[i].eventtype=="chord"){nevts_ch.push_back(hom.evts[i]); curType=2;
				}else if(hom.evts[i].eventtype=="tremolo"){nevts_tm.push_back(hom.evts[i]); curType=3;
				}//endif
				curStime=hom.evts[i].stime;
			}//endif
		}//endfor i

}//

// cerr<<"&&&&&&&&&&&&&&& 3"<<endl;

		//// Find duplicate onsets
		DuplicateOnsetEvt dup;
		int preStime=-1;
		vector<vector<vector<int> > > indecesPerPitch;//indecesPerPitch[p][j][0,1]=k,l for evts[i].sitchesPerCluster[k][l]
		vector<int> vi(2);
		vector<string> uniqueFmt1IDs;
		for(int i=0;i<evts.size();i+=1){
			indecesPerPitch.clear();
			indecesPerPitch.resize(128);
			for(int k=0;k<evts[i].numClusters;k+=1)for(int l=0;l<evts[i].numNotesPerCluster[k];l+=1){

// if(SitchToPitch(evts[i].sitchesPerCluster[k][l])<0 || SitchToPitch(evts[i].sitchesPerCluster[k][l])>127){
// cerr<<evts[i].stime<<" "<<evts[i].sitchesPerCluster[k][l]<<endl;
// }//endif

				vi[0]=k; vi[1]=l;
				indecesPerPitch[SitchToPitch(evts[i].sitchesPerCluster[k][l])].push_back(vi);
			}//endfor k,l

			for(int p=0;p<128;p+=1){
				if(indecesPerPitch[p].size()<=1){continue;}
				uniqueFmt1IDs.clear();
				for(int j=0;j<indecesPerPitch[p].size();j+=1){
					if(find(uniqueFmt1IDs.begin(),uniqueFmt1IDs.end(),evts[i].fmt1IDsPerCluster[indecesPerPitch[p][j][0]][indecesPerPitch[p][j][1]])==uniqueFmt1IDs.end()){
						uniqueFmt1IDs.push_back(evts[i].fmt1IDsPerCluster[indecesPerPitch[p][j][0]][indecesPerPitch[p][j][1]]);
					}//endif
				}//endfor j
				if(uniqueFmt1IDs.size()<=1){continue;}
				dup.stime=evts[i].stime;
				dup.sitch=evts[i].sitchesPerCluster[indecesPerPitch[p][0][0]][indecesPerPitch[p][0][1]];
				dup.numOnsets=uniqueFmt1IDs.size();
				dup.fmt1IDs.clear();
				for(int j=uniqueFmt1IDs.size()-1;j>=0;j-=1){
					dup.fmt1IDs.push_back(uniqueFmt1IDs[j]);
				}//endfor j
				duplicateOnsets.push_back(dup);
			}//endfor p

			preStime=evts[i].stime;
		}//endfor i

	}//end ConvertFromHom


	void ConvertFromFmt3x(Fmt3x fmt3x){
		Clear();
		TPQN=fmt3x.TPQN;

{
		HmmEvt evt;
		evt.numNotesPerCluster.resize(1);
		evt.sitchesPerCluster.resize(1);
		evt.voicesPerCluster.resize(1);
		evt.fmt1IDsPerCluster.resize(1);
		vector<int> vi;

		for(int i=0;i<fmt3x.evts.size();i+=1){
			evt.stime=fmt3x.evts[i].stime;
			evt.endstime=fmt3x.evts[i].stime;
			evt.internalPosition=1;
			evt.stateType="CH";

			evt.numClusters=1;
			evt.numSitches=fmt3x.evts[i].numNotes;
			evt.numCh=fmt3x.evts[i].numNotes-1;
			evt.numArp=0;
			evt.numInterCluster=0;

			evt.numNotesPerCluster[0]=fmt3x.evts[i].numNotes;
			evt.sitchesPerCluster[0]=fmt3x.evts[i].sitches;
			vi.assign(fmt3x.evts[i].numNotes,0);
			evt.voicesPerCluster[0]=vi;
			evt.fmt1IDsPerCluster[0]=fmt3x.evts[i].fmt1IDs;

			evts.push_back(evt);
		}//endfor i
}//

		for(int i=0;i<fmt3x.duplicateOnsets.size();i+=1){
			DuplicateOnsetEvt dup;
			dup.stime=fmt3x.duplicateOnsets[i].stime;
			dup.sitch=fmt3x.duplicateOnsets[i].sitch;
			dup.numOnsets=fmt3x.duplicateOnsets[i].numOnsets;
			dup.fmt1IDs=fmt3x.duplicateOnsets[i].fmt1IDs;
			duplicateOnsets.push_back(dup);
		}//endfor i

	}//end ConvertFromFmt3x

	void ResetInternalPosition(){//AN have negative internal positions
		int preStime=-1000;
		int NTmpEvts=0;
		int numANs=0;
		for(int i=0;i<evts.size();i+=1){
			if(evts[i].stime!=preStime){
				for(int i_=i-1;i_>=i-NTmpEvts;i_-=1){
					evts[i_].internalPosition-=numANs;
				}//endfor i_
				preStime=evts[i].stime;
				NTmpEvts=0;
				numANs=0;
			}//endif

			NTmpEvts+=1;
			if(evts[i].stateType=="AN"){
				numANs+=1;
			}//endif

		}//endfor i
		for(int i_=evts.size()-1;i_>=evts.size()-NTmpEvts;i_-=1){
			evts[i_].internalPosition-=numANs;
		}//endfor i_

	}//end ResetInternalPosition


	bool IsDuplicate(string fmt1ID_){
		bool found=false;
		for(int i=0;i<duplicateOnsets.size();i+=1){
			for(int j=1;j<duplicateOnsets[i].numOnsets;j+=1){
				if(fmt1ID_==duplicateOnsets[i].fmt1IDs[j]){
					found=true;
					break;
				}//endif
			}//endfor j
		}//endfor i
		return found;
	}//end IsDuplicate

};//endclass Hmm

#endif // Hmm_HPP
