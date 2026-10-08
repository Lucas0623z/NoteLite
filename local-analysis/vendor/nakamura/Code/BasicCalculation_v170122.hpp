#ifndef BasicCalculation_HPP
#define BasicCalculation_HPP

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
#include<random>
#include<climits>
using namespace std;

mt19937_64 mt_(0);
uniform_real_distribution<> rand1_(0,1);
uniform_int_distribution<> rand1int_(0,INT_MAX);
// mt_=mt19937_64(seed);

inline double RandDouble(){//between 0 and 1
	return rand1_(mt_);
//	return (1.0*rand())/(1.0*RAND_MAX);
}//end

inline int RandInt(){//between 0 and int-max
	return rand1int_(mt_);
//	return mt_();
}//end

inline void SetSeedRand(int seed){
	mt_=mt19937_64(seed);
}//end 

inline void SetSeed(int seed){
	mt_=mt19937_64(seed);
}//end 

inline int gcd(int m, int n){
	if(0==m||0==n){return 0;}
	while(m!=n){if(m>n){m=m-n;}else{n=n-m;}}//endwhile
	return m;
}//end gcd
inline int lcm(int m,int n){
	if (0==m||0==n){return 0;}
	return ((m/gcd(m,n))*n);//lcm=m*n/gcd(m,n)
}//end lcm

inline double LogAdd(double d1,double d2){
	//log(exp(d1)+exp(d2))=log(exp(d1)(1+exp(d2-d1)))
	if(d1>d2){
//		if(d1-d2>20){return d1;}
		return d1+log(1+exp(d2-d1));
	}else{
//		if(d2-d1>20){return d2;}
		return d2+log(1+exp(d1-d2));
	}//endif
}//end LogAdd

inline double Sum(vector<double>& vd){
	double sum=0;
	for(int i=0;i<vd.size();i++){sum+=vd[i];}
	return sum;
}//end Sum
inline int Sum(vector<int>& vi){
	int sum=0;
	for(int i=0;i<vi.size();i++){sum+=vi[i];}
	return sum;
}//end Sum

inline void Norm(vector<double>& vd){
	double sum=0;
	for(int i=0;i<vd.size();i+=1){sum+=vd[i];}//endif
	for(int i=0;i<vd.size();i+=1){vd[i]/=sum;}
}//end Norm
inline void Normalize(vector<double>& vd){
	Norm(vd);
}//end Normalize

inline void Lognorm(vector<double>& vd){
	double tmpd=vd[0];
	for(int i=0;i<vd.size();i+=1){if(vd[i]>tmpd){tmpd=vd[i];}}//endfor i
	for(int i=0;i<vd.size();i+=1){vd[i]-=tmpd;}//endfor i
	tmpd=0;
	for(int i=0;i<vd.size();i+=1){tmpd+=exp(vd[i]);}//endfor i
	tmpd=log(tmpd);
	for(int i=0;i<vd.size();i+=1){vd[i]-=tmpd;if(vd[i]<-200){vd[i]=-200;}}//endfor i
}//end Lognorm

inline double SqNorm(vector<double>& vd){
	double sum=0;
	for(int i=0;i<vd.size();i+=1){
		sum+=vd[i]*vd[i];
	}//endif
	sum=pow(sum,0.5);
	for(int i=0;i<vd.size();i+=1){vd[i]/=sum;}
	return sum;
}//end SqNorm

inline double Mean(vector<double>& vd){
	assert(vd.size()>0);
	double sum=0;
	for(int i=0;i<vd.size();i+=1){
		sum+=vd[i];
	}//endfor i
	return sum/double(vd.size());
}//end Mean

inline double Average(vector<double>& vd){
	assert(vd.size()>0);
	double sum=0;
	for(int i=0;i<vd.size();i+=1){
		sum+=vd[i];
	}//endfor i
	return sum/double(vd.size());
}//end Average

inline double StDev(vector<double>& vd){
	assert(vd.size()>0);
	if(vd.size()==1){return 0;}
	double ave=Average(vd);
	double sum=0;
	for(int i=0;i<vd.size();i+=1){
		sum+=pow(vd[i]-ave,2.);
	}//endfor i
	return pow(sum/double(vd.size()-1),0.5);
}//end StDev

inline double SampleSkewness(vector<double>& vd, double mu, double sig){
//Calculate G1
	assert(vd.size()>0);
	if(vd.size()<3){return 0;}
	double mu3=0;
	for(int i=0;i<vd.size();i+=1){
		mu3+=pow(vd[i]-mu,3.);
	}//endfor i
	mu3=mu3*double(vd.size())/(double(vd.size()-1)*double(vd.size()-2));
//	mu3=mu3/double(vd.size());
//cout<<vd.size()<<endl;
	return mu3/pow(sig,3.);
}//end SampleSkewness

inline double SampleKurtosis(vector<double>& vd, double mu, double sig){
//Calculate G2
	assert(vd.size()>0);
	if(vd.size()<5){return 0;}
	double mu4=0;
	for(int i=0;i<vd.size();i+=1){
		mu4+=pow(vd[i]-mu,4.);
	}//endfor i
	double n=double(vd.size());
	return (((n+1)*n)/((n-1)*(n-2)*(n-3)))*(mu4/pow(sig,4.))-3*(n-1)*(n-1)/((n-2)*(n-3));
//	return (mu4/n)/pow(sig,4.)-3;
//	mu4/=double(vd.size());
//	return mu4/pow(sig,4.)-3;
}//end SampleKurtosis

inline double Median(vector<double> vd){
	assert(vd.size()>0);
	sort(vd.begin(),vd.end());
	if(vd.size()%2==1){
		return vd[vd.size()/2];
	}else{
		return 0.5*(vd[vd.size()/2-1]+vd[vd.size()/2]);
	}//endif
}//end Median

inline double FirstQuartile(vector<double> vd){
	assert(vd.size()>0);
	sort(vd.begin(),vd.end());
	int nOrg=vd.size();
	for(int i=nOrg-1;i>=nOrg/2;i-=1){
		vd.erase(vd.begin()+i);
	}//endfor i
	return Median(vd);
}//end FirstQuartile

inline double ThirdQuartile(vector<double> vd){
	assert(vd.size()>0);
	sort(vd.begin(),vd.end());
	int nOrg=vd.size();
	for(int i=nOrg-1;i>=nOrg/2;i-=1){
		vd.erase(vd.begin());
	}//endfor i
	return Median(vd);
}//end ThirdQuartile

inline double GetCorrelation(vector<double> &data1, vector<double> &data2){
	assert(data1.size()==data2.size());

	double mu1=Mean(data1);
	double mu2=Mean(data2);
	double sig1=StDev(data1);
	double sig2=StDev(data2);

	double corr=0;
	for(int i=0;i<data1.size();i+=1){
		corr+=(data1[i]-mu1)*(data2[i]-mu2);
	}//endfor i
	corr/=double(data1.size()-1);
	corr/=(sig1*sig2);
	return corr;
}//end GetCorrelation

inline double GetMax(vector<double>& vd){
	assert(vd.size()>0);
	double max=vd[0];
	for(int i=0;i<vd.size();i+=1){
		if(vd[i]>max){max=vd[i];}
	}//endfor i
	return max;
}//end GetMax
inline double GetMin(vector<double>& vd){
	assert(vd.size()>0);
	double min=vd[0];
	for(int i=0;i<vd.size();i+=1){
		if(vd[i]<min){min=vd[i];}
	}//endfor i
	return min;
}//end GetMin

double SqDist(vector<double> &p,vector<double> &q,double scale=1){//p given q
	assert(p.size()==q.size());
	double sum=0;
	for(int i=0;i<p.size();i+=1){
		sum+=pow((p[i]-q[i])/scale,2.);
	}//endfor p
	return sum;
}//end SqDist

inline int SampleDistr(vector<double> &p){
//	double val=(1.0*rand())/(1.0*RAND_MAX);
	double val=rand1_(mt_);
	for(int i=0;i<p.size()-1;i+=1){
		if(val<p[i]){return i;
		}else{val-=p[i];
		}//endif
	}//endfor i
	return p.size()-1;
}//end SampleDistr

inline double RandDoubleInRange(double from,double to){
	return (1.0*rand())/(1.0*RAND_MAX)*(to-from)+from;
}//end

// inline double SampleGauss(double mu,double stdev){
// 	double x,y;
// 	x=(1.*rand())/(1.*RAND_MAX);
// 	y=(1.*rand())/(1.*RAND_MAX);
// 	return sqrt(-1*log(x))*cos(2*M_PI*y)*stdev+mu;
// }//end

inline vector<double> LinearRegression(vector<double> dataX,vector<double> dataY){
	assert(dataX.size()==dataY.size());
	int nSample=dataX.size();
	double xbar=Mean(dataX);
	double ybar=Mean(dataY);
	double xybar,x2bar;

	x2bar=0;
	for(int i=0;i<nSample;i+=1){
		x2bar+=dataX[i]*dataX[i];
	}//endfor i
	x2bar/=double(nSample);

	xybar=0;
	for(int i=0;i<nSample;i+=1){
		xybar+=dataX[i]*dataY[i];
	}//endfor i
	xybar/=double(nSample);

	vector<double> ret(2);//[0,1]=a,b
	ret[0]=(xybar-xbar*ybar)/(x2bar-xbar*xbar);
	ret[1]=(xybar-ret[0]*x2bar)/xbar;

	return ret;
}//end LinearRegression

class Pair{
public:
	int ID;
	double value;

	Pair(){
	}//end Pair
	Pair(int ID_,double value_){
		ID=ID_;
		value=value_;
	}//end Pair
	~Pair(){
	}//end ~Pair

};//endclass Pair

class MorePair{
public:
	bool operator()(const Pair& a, const Pair& b){
		if(a.value > b.value){
			return true;
		}else{//if a.value <= b.value
			return false;
		}//endif
	}//end operator()
};//end class MorePair
//sort(pairs.begin(), pairs.end(), MorePair());
class LessPair{
public:
	bool operator()(const Pair& a, const Pair& b){
		if(a.value < b.value){
			return true;
		}else{//if a.value <= b.value
			return false;
		}//endif
	}//end operator()
};//end class LessPair
//sort(pairs.begin(), pairs.end(), LessPair());

inline vector<Pair> GetPair(vector<double> &vd){
	vector<Pair> ret;
	Pair pair;
	for(int i=0;i<vd.size();i++){
		pair.ID=i;
		pair.value=vd[i];
		ret.push_back(pair);
	}//endfor i
	return ret;
}//end GetPair

inline vector<double> Intervals(double valmin,double valmax,int nPoint){
	vector<double> values;
	double eps=(valmax-valmin)/double(nPoint-1);
	for(int i=0;i<nPoint;i+=1){
		values.push_back( valmin+i*eps );
	}//endfor i
	return values;
}//end Intervals

inline vector<double> LogIntervals(double valmin,double valmax,int nPoint){
	vector<double> values;
	double eps=(log(valmax)-log(valmin))/double(nPoint-1);
	for(int i=0;i<nPoint;i+=1){
		values.push_back( valmin*exp(i*eps) );
	}//endfor i
	return values;
}//end LogIntervals

inline vector<int> RandomOrderVector(int nSize){
	srand(2);
	vector<int> cand,res;
	for(int n=0;n<nSize;n+=1){
		cand.push_back(n);
	}//endfor n
	int sample;
	while(cand.size()>0){
		sample=rand()%cand.size();
		res.push_back(cand[sample]);
		cand.erase(cand.begin()+sample);
	}//endwhile
	return res;
}//end RandomOrderVector

//From Prob_v160925.hpp
template <typename T> class Prob{
public:
	vector<double> P;
	vector<double> LP;
	vector<T> samples;

	Prob(){
	}//end Prob
	Prob(Prob<T> const & prob_){
		P=prob_.P;
		LP=prob_.LP;
		samples=prob_.samples;
	}//end Prob
	Prob(int dim){
		Resize(dim);
	}//end Prob

	~Prob(){
	}//end ~Prob

	Prob& operator=(const Prob<T> & prob_){
		P=prob_.P;
		LP=prob_.LP;
		samples=prob_.samples;
		return *this;
	}//end =

	void Print(){
		for(int i=0;i<P.size();i+=1){
cout<<i<<"\t"<<samples[i]<<"\t"<<P[i]<<"\t"<<LP[i]<<endl;
		}//endfor i
	}//end Print

	void Normalize(){
		Norm(P);
		PToLP();
	}//end Normalize

	void LogNormalize(){
		Lognorm(LP);
		LPToP();
	}//end Normalize

	void PToLP(){
		LP.clear();
		LP.resize(P.size());
		for(int i=0;i<P.size();i+=1){
			LP[i]=log(P[i]);
		}//endfor i
	}//end PToLP

	void LPToP(){
		P.clear();
		P.resize(LP.size());
		for(int i=0;i<LP.size();i+=1){
			P[i]=exp(LP[i]);
		}//endfor i
	}//end LPToP

	T Sample(){
		return samples[SampleDistr(P)];
	}//end Sample

	void Clear(){
		P.clear(); LP.clear(); samples.clear();
	}//end Clear

	void Resize(int _size){
		P.clear(); LP.clear(); samples.clear();
		P.resize(_size);
		LP.resize(_size);
		samples.resize(_size);
	}//end Resize

	void Assign(int _size,double value){
		P.clear(); LP.clear(); samples.clear();
		P.assign(_size,value);
		LP.resize(_size);
		samples.resize(_size);
	}//end Assign

	double MaxP(){
		double max=P[0];
		for(int i=1;i<P.size();i+=1){
			if(P[i]>max){max=P[i];}
		}//endfor i
		return max;
	}//end MaxValue

	int ModeID(){
		double max=P[0];
		int modeID=0;
		for(int i=1;i<P.size();i+=1){
			if(P[i]>max){modeID=i;}
		}//endfor i
		return modeID;
	}//end ModeID

	void Randomize(){
		for(int i=0;i<P.size();i+=1){
			P[i]=RandDouble();
//			P[i]=(1.0*rand())/(1.0*RAND_MAX);
		}//endfor i
		Normalize();
	}//end Randomize

	void ChangeTemperature(double beta){
		for(int i=0;i<P.size();i+=1){
			P[i]=pow(P[i],beta);
		}//endfor i
		Normalize();
	}//end ChangeTemperature

	void Sort(){
		vector<Pair> pairs;
		Pair pair;
		for(int i=0;i<P.size();i+=1){
			pair.ID=i;
			pair.value=P[i];
			pairs.push_back(pair);
		}//endfor i
		stable_sort(pairs.begin(), pairs.end(), MorePair());

		Prob<T> tmpProb;
		tmpProb=*this;
		for(int i=0;i<P.size();i+=1){
			P[i]=tmpProb.P[pairs[i].ID];
			samples[i]=tmpProb.samples[pairs[i].ID];
		}//endfor i
		PToLP();

	}//end Sort

	double Entropy(){
		double ent=0;
		for(int i=0;i<P.size();i+=1){
			if(P[i]<1E-10){continue;}
			ent+=-P[i]*log(P[i]);
		}//endfor i
		return ent;
	}//end Entropy

	double SelfMatchProb(){
		double smp=0;
		for(int i=0;i<P.size();i+=1){
			smp+=P[i]*P[i];
		}//endfor i
		return smp;
	}//end SelfMatchProb

};//endclass Prob

inline Prob<int> GetStatProb(vector<Prob<int> > trProb,int nIter=300){
	Prob<int> statProb;
	statProb.Resize(trProb.size());
	for(int i=0;i<trProb.size();i+=1){statProb.P[i]=1;}
	statProb.Normalize();
	Prob<int> _statProb;
	for(int iter=0;iter<nIter;iter+=1){
		_statProb=statProb;
		for(int i=0;i<trProb.size();i+=1){
			statProb.P[i]=0;
			for(int ip=0;ip<trProb.size();ip+=1){
				statProb.P[i]+=_statProb.P[ip]*trProb[ip].P[i];
			}//endfor ip
		}//endfor i
		statProb.Normalize();
	}//endfor iter
	return statProb;
}//end GetStatProb

inline double EntropyRate(vector<Prob<int> > trProb,int nIter=300){
	Prob<int> statProb;
	statProb=GetStatProb(trProb,nIter);
	double ent=0;
	for(int i=0;i<statProb.P.size();i+=1){
		ent+=statProb.P[i]*trProb[i].Entropy();
	}//endfor i
	return ent;
}//end EntropyRate

inline double CrossEntropy(vector<double> Ptrue,vector<double> Pest){
	assert(Ptrue.size()==Pest.size());
	double sum=0;
	for(int n=0;n<Ptrue.size();n+=1){
		if(Pest[n]<1E-100){
			sum+=Ptrue[n]*1000;
		}else{
			sum+=-Ptrue[n]*log(Pest[n]);
		}//endif
	}//endfor n
	return sum;
}//end CrossEntropy

inline double MatchProb(vector<double> Ptrue,vector<double> Pest){
	assert(Ptrue.size()==Pest.size());
	double sum=0;
	for(int n=0;n<Ptrue.size();n+=1){
		sum+=Ptrue[n]*Pest[n];
	}//endfor n
	return sum;
}//end MatchProb

inline double KLDiv(vector<double> &p,vector<double> &q,double regularizer){//p given q
	assert(p.size()==q.size());
	double sum=0;
	for(int i=0;i<p.size();i+=1){
		if(p[i]<1E-100){continue;}
		sum+=p[i]*(log(p[i])-log(q[i]+regularizer));
	}//endfor p
	return sum;
}//end KLDiv

inline double SymKLDiv(vector<double> &p,vector<double> &q,double regularizer){
	return KLDiv(p,q,regularizer)+KLDiv(q,p,regularizer);
}//end SymKLDiv

inline double JSDiv(vector<double> &p,vector<double> &q){
	assert(p.size()==q.size());
	double ret=0;
	for(int i=0;i<p.size();i++){
		if(p[i]>1E-100){
			ret+=p[i]*log(p[i]/(p[i]+q[i]));
		}//endif
		if(q[i]>1E-100){
			ret+=q[i]*log(q[i]/(p[i]+q[i]));
		}//endif
	}//endfor i
	return log(2)+0.5*ret;
}//end JSDiv


class TemporalDataSample{
public:
	string label;
	double time;
	int dimValue;
	vector<double> values;
};//endclass TemporalSample

class TemporalData{
public:
	vector<int> refTimes;//E.g. 1900,2000 => intervals are (-inf,1900) [1900,2000) [2000,inf)
	vector<TemporalDataSample> data;
	vector<vector<vector<double> > > statistics;//(refYears.size+1)xdimValuex3; #samples,mean,stdev
	int dimValue;

	void PrintTimeIntervals(){
		cout<<"(-inf,"<<refTimes[0]<<")"<<endl;
		for(int i=1;i<refTimes.size();i+=1){
			cout<<"["<<refTimes[i-1]<<","<<refTimes[i]<<")"<<endl;
		}//endfor i
		cout<<"["<<refTimes[refTimes.size()-1]<<",inf)"<<endl;
	}//end PrintTimeIntervals

	void PrintStatistics(){
		cout<<"#(-inf,"<<refTimes[0]<<")"<<"\t"<<refTimes[0]<<"\t"<<statistics[0][0][0];
		for(int k=0;k<statistics[0].size();k+=1){
			cout<<"\t"<<statistics[0][k][1]<<"\t"<<statistics[0][k][2];
		}//endfor k
		cout<<endl;
		for(int i=1;i<refTimes.size();i+=1){
			cout<<"["<<refTimes[i-1]<<","<<refTimes[i]<<")"<<"\t"<<0.5*(refTimes[i-1]+refTimes[i])<<"\t"<<statistics[i][0][0];
			for(int k=0;k<statistics[0].size();k+=1){
				cout<<"\t"<<statistics[i][k][1]<<"\t"<<statistics[i][k][2];
			}//endfor k
			cout<<endl;
		}//endfor i
		cout<<"#["<<refTimes[refTimes.size()-1]<<",inf)"<<"\t"<<refTimes[refTimes.size()-1]<<"\t"<<statistics[refTimes.size()][0][0];
		for(int k=0;k<statistics[0].size();k+=1){
			cout<<"\t"<<statistics[refTimes.size()][k][1]<<"\t"<<statistics[refTimes.size()][k][2];
		}//endfor k
		cout<<endl;
	}//end PrintStatistics

	void AddDataSample(TemporalDataSample sample){
		data.push_back(sample);
	}//end AddDataSample

	void Analyze(){
		vector<vector<vector<double> > > values;
		values.resize(refTimes.size()+1);
		int timeID;
		for(int n=0;n<data.size();n+=1){
			timeID=0;
			for(int i=0;i<refTimes.size();i+=1){
				if(data[n].time>=refTimes[i]){timeID=i+1;
				}else{break;
				}//endif
			}//endfor i
			values[timeID].push_back(data[n].values);
		}//endfor n
		dimValue=data[0].dimValue;

		statistics.clear();
		statistics.resize(refTimes.size()+1);
		for(int i=0;i<statistics.size();i+=1){
			statistics[i].resize(dimValue);
			for(int k=0;k<dimValue;k+=1){
				statistics[i][k].resize(3);
				vector<double> vd;
				for(int n=0;n<values[i].size();n+=1){
					vd.push_back(values[i][n][k]);
				}//endfor n
				statistics[i][k][0]=vd.size();
				if(statistics[i][k][0]==0){
				}else if(statistics[i][k][0]==1){
					statistics[i][k][1]=vd[0];
					statistics[i][k][2]=0;
				}else{
					statistics[i][k][1]=Average(vd);
					statistics[i][k][2]=StDev(vd);
				}//endif

			}//endfor k
		}//endfor i

	}//end Analyze

};//endclass TemporalData

// inline void DeleteHeadSpace(string &buf){
// 	size_t pos;
// 	while((pos = buf.find_first_of(" 　\t")) == 0){
// 		buf.erase(buf.begin());
// 		if(buf.empty()) break;
// 	}//endwhile
// }//end DeleteHeadSpace

// inline vector<string> UnspaceString(string str){
// 	vector<string> vs;
// 	while(str.size()>0){
// 		DeleteHeadSpace(str);
// 		if(str=="" || isspace(str[0])!=0){break;}
// 		vs.push_back(str.substr(0,str.find_first_of(" \t")));
// 		for(int i=0;i<vs[vs.size()-1].size();i+=1){str.erase(str.begin());}
// 	}//endwhile
// 	return vs;
// }//end UnspaceString

// vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
// [20200527] modified by nishikimi
inline bool starts_with(
    const std::string& s, const std::string& c, const int start = 0)
{
  return s.substr(start, c.size()) == c;
}

template <int N>
inline std::size_t starts_with(
    const std::string& s, const std::string (&cs)[N], const int start = 0)
{
  for (int i = 0; i < N; i++) if (starts_with(s, cs[i], start)) {
    return cs[i].size();
  }
  return 0;
}

inline int find_first_blank_pos(const std::string&s, const int start = 0)
{
  static const std::string BLANKS[] = { " ", "\t", "　" };

  std::size_t i = start;
  while (i < s.size() && !starts_with(s, BLANKS, i)) { i++; };
  return i;
}

inline int find_first_noblank_pos(const std::string& s, const int start = 0)
{
  static const std::string BLANKS[] = { " ", "\t", "　" };

  std::size_t i = start, n;
  while (i < s.size() && (n = starts_with(s, BLANKS, i))) { i += n; }
  return i;
}

inline void remove_leading_space(std::string &s)
{
  s.erase(s.begin(), s.begin() + find_first_noblank_pos(s));
}

inline std::vector<std::string> split(const std::string& s)
{
  std::vector<std::string> res;
  std::size_t first = 0;
  std::size_t last  = 0;
  while (first < s.size()) {
    first = find_first_noblank_pos(s, last);
    last  = find_first_blank_pos(s, first);
    if (first < s.size()) res.push_back(s.substr(first, last-first));
  }
  return res;
}

inline void DeleteHeadSpace(std::string& s) { remove_leading_space(s); }
inline std::vector<std::string> UnspaceString(const string& s) { return split(s); }
// ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

template <class T> void GetPowerSet(vector<T> const &set, vector<T> &subset, vector<vector<T> > &powerset,int n){
	if(n>30){cerr<<"too large set"<<endl; return;}
	if(n==0){powerset.push_back(subset); return;}//endif
	// consider nth element
	subset.push_back(set[n-1]);
	GetPowerSet(set,subset,powerset,n-1);
	// or don't consider nth element
	subset.pop_back();
	GetPowerSet(set,subset,powerset,n-1);
}//end GetPowerSet
//Usage: vector<T> S,SS; vector<vector<T> > PS; int setSize=S.size(); GetPowerSet(S,SS,PS,setSize);

template <class T> void GetPermutationSet(vector<T> &set, vector<vector<T> > &permset){
	permset.clear();
    do{
    	permset.push_back(set);
    }while( next_permutation(set.begin(), set.end()) );
}//end GetPermutationSet
//Usage: vector<T> S; vector<vector<T> > PS; GetPermutationSet(S,PS);

template <class T> void SubstituteVector(vector<T> &vec,string str,bool clear=true){
	if(clear){vec.clear();}
	stringstream ss;
	ss<<str;
	T val;
	while(ss>>val){
		vec.push_back(val);
	}//endwhile
}//end SubstituteVector

template <class T> vector<T> DistinctElements(vector<T> vec){
	vector<T> distinct;
	for(int i=0;i<vec.size();i+=1){
		if(find(distinct.begin(),distinct.end(),vec[i])==distinct.end()){
			distinct.push_back(vec[i]);
		}//endif
	}//endfor i
	return distinct;
}//end DistinctElements

template <class T> void PrintVector(vector<T> &vec){
	for(int i=0;i<vec.size();i+=1){
cout<<i<<"\t"<<vec[i]<<endl;
	}//endfor i
}//end PrintVector

template <class T> void SplitCVData(vector<T> names,vector<vector<T> > &trainData,vector<vector<T> > &testData,int foldSize){
	trainData.clear(); testData.clear();
	vector<int> splitPos;
	for(int i=0;i<foldSize;i+=1){
		splitPos.push_back( (i*names.size())/foldSize );
	}//endfor i
	trainData.resize(foldSize); testData.resize(foldSize);
	for(int i=0;i<foldSize;i+=1){
		for(int n=0;n<splitPos[i];n+=1){
			trainData[i].push_back(names[n]);
		}//endfor n
		if(i==foldSize-1){
			for(int n=splitPos[i];n<names.size();n+=1){
				testData[i].push_back(names[n]);
			}//endfor n
		}else{
			for(int n=splitPos[i];n<splitPos[i+1];n+=1){
				testData[i].push_back(names[n]);
			}//endfor n
			for(int n=splitPos[i+1];n<names.size();n+=1){
				trainData[i].push_back(names[n]);
			}//endfor n
		}//endif
	}//endfor i
}//end SplitCVData

inline string GetDatetimeStr(){
	time_t t = time(nullptr);
	const tm* localTime = localtime(&t);
	std::stringstream ss;
	ss << "20" << localTime->tm_year - 100<<"/";
	ss << setw(2) << setfill('0') << localTime->tm_mon + 1<<"/";
	ss << setw(2) << setfill('0') << localTime->tm_mday<<"-";
	ss << setw(2) << setfill('0') << localTime->tm_hour<<":";
	ss << setw(2) << setfill('0') << localTime->tm_min<<":";
	ss << setw(2) << setfill('0') << localTime->tm_sec;
	return ss.str();
}//end GetDatetimeStr


template <class T> vector<T> GetRandomPermutation(vector<T> vec){
	vector<T> ret;
	vector<int> candpos;
	for(int i=0;i<vec.size();i+=1){candpos.push_back(i);}//endfor i
	int cand;
	while(true){
		cand=RandInt()%candpos.size();
		ret.push_back(vec[candpos[cand]]);
		candpos.erase(candpos.begin()+cand);
		if(candpos.size()==0){break;}
	}//endwhile
	return ret;
}//end GetRandomPermutation

template <class T> int FindPos(vector<T> &vec, T value){
	return find(vec.begin(),vec.end(),value)-vec.begin();
}//end FindPos

inline void EPrint(string s){
cout<<s+s+s+s+s+s+s<<endl;
}//end EPrint


#endif // BasicCalculation_HPP
