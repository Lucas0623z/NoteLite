"""NoteWise capability-aware recorded analysis and independent evidence arbitration.

The selected score supplies instrument identity and whether the excerpt overlaps.
No expected note identities or timing enter the acoustic detectors/arbitrator.
Original detector traces and unresolved disagreements remain in the result.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

POLICY_VERSION = "notewise-fusion-1"
CREPE_SAFE_MIN_HZ = 50.0
CREPE_MAX_HZ = 1975.6

def profile_registry(home=None):
    """One generated registry is shared with the web and Apple implementations.

    An installed registry is authoritative, including when invalid. The source
    fallback only supports development; never silently mask an invalid package.
    """
    installed=Path(home or Path(__file__).parent)/"NoteWiseProfiles.json"
    source=Path(__file__).resolve().parent.parent/"apple"/"NoteLite"/"NoteWiseProfiles.json"
    path=installed if installed.is_file() else source
    if not path.is_file() or path.stat().st_size>256*1024:
        raise ValueError("NoteWise instrument registry is missing or too large")
    stamp=path.stat()
    return _validated_registry(str(path.resolve()),stamp.st_mtime_ns,stamp.st_size)


@lru_cache(maxsize=4)
def _validated_registry(filename,mtime_ns,size):
    path=Path(filename)
    registry=json.loads(path.read_text(encoding="utf8"))
    rows=registry.get("profiles") if isinstance(registry,dict) else None
    policy=registry.get("fusionPolicy",{})
    if registry.get("schemaVersion")!=1 or not isinstance(rows,list) or not 1<=len(rows)<=128 or policy.get("version")!=POLICY_VERSION:
        raise ValueError("Invalid NoteWise instrument registry version")
    ids=set()
    for row in rows:
        if (not isinstance(row,dict) or not isinstance(row.get("id"),str) or row["id"] in ids
            or row.get("family") not in ("keyboard","bowed","plucked","wind","voice","generic")
            or not all(isinstance(row.get(k),int) and not isinstance(row.get(k),bool) for k in ("minMidi","maxMidi"))
            or not 0<=row["minMidi"]<row["maxMidi"]<=127 or not isinstance(row.get("variants"),list)):
            raise ValueError("Invalid NoteWise instrument profile")
        ids.add(row["id"])
        variant_ids=set()
        for variant in row["variants"]:
            if (not isinstance(variant,dict) or not isinstance(variant.get("id"),str) or variant["id"] in variant_ids
                or not isinstance(variant.get("transpose"),int) or not -48<=variant["transpose"]<=48):
                raise ValueError("Invalid NoteWise instrument notation variant")
            variant_ids.add(variant["id"])
    mono=policy.get("mono",{})
    if (mono.get("windowsPrimary")!="pyin" or mono.get("windowsReview")!="crepe"
        or policy.get("poly",{}).get("primary")!="basic-pitch"
        or mono.get("reviewMinimumHz")!=CREPE_SAFE_MIN_HZ or mono.get("reviewMaximumHz")!=CREPE_MAX_HZ
        or not .01<=mono.get("onsetToleranceSeconds",0)<=.3 or not 1<=mono.get("centsTolerance",0)<=100):
        raise ValueError("Unsupported NoteWise fusion policy")
    return registry


def profile_policy(instrument,home=None):
    return next((p for p in profile_registry(home)["profiles"] if p["id"]==instrument),None)


def plan_recording(parts, polyphonic, a4=440,home=None):
    if not isinstance(parts,list) or not parts or len(parts)>128:
        raise ValueError("NoteWise requires the actual selected normalized instrument parts")
    if not isinstance(polyphonic,bool):
        raise ValueError("NoteWise requires the actual selected excerpt polyphony")
    if isinstance(a4,bool) or not isinstance(a4,(int,float)) or not math.isfinite(a4) or not 400<=a4<=480:
        raise ValueError("Invalid NoteWise tuning")
    registry=profile_registry(home);profiles={p["id"]:p for p in registry["profiles"]}
    requires=[]; definitions=[]; ids=[];diagnostics=[]
    for part in parts:
        if not isinstance(part,dict): raise ValueError("Invalid normalized instrument part")
        instrument=part.get("instrument")
        definition=profiles.get(instrument)
        if not definition or part.get("reliable") is not True:
            requires.append({"partId":part.get("id"),"reason":"instrument-unconfirmed"})
            continue
        for reason in part.get("requiresConfirmation",[]):
            requires.append({"partId":part.get("id"),"reason":reason})
        if part.get("transpositionConfirmed") is not True:
            requires.append({"partId":part.get("id"),"reason":"transposition-unconfirmed"})
        mapped=part.get("instrumentIds",[instrument])
        if not isinstance(mapped,list) or not mapped or any(i not in profiles for i in mapped):
            requires.append({"partId":part.get("id"),"reason":"instrument-mapping-unresolved"});continue
        if len(set(mapped))>1:
            if part.get("instrumentMappingResolved") is not True or polyphonic or len({profiles[i]["family"] for i in mapped})!=1:
                requires.append({"partId":part.get("id"),"reason":"instrument-mapping-unresolved"})
            else: diagnostics.append("Explicit sequential same-family instrument mapping uses the union of sounding ranges.")
        definitions.extend(profiles[i] for i in mapped);ids.extend(mapped)
    if len(parts)>1 and len(set(ids))>1:
        requires.append({"reason":"multiple-acoustic-instruments"})
    if requires:
        raise ValueError("Confirm the selected instrument and sounding-pitch notation before NoteWise analysis: "+json.dumps(requires,ensure_ascii=False))
    family=definitions[0]["family"] if len({p["family"] for p in definitions})==1 else "generic"
    mode="poly" if polyphonic or family in ("keyboard","plucked") else "mono"
    minimum=min(p["minMidi"] for p in definitions);maximum=max(p["maxMidi"] for p in definitions)
    return {"policyVersion":POLICY_VERSION,"mode":mode,"primary":"basic-pitch" if mode=="poly" else "pyin",
            "validators":[registry["fusionPolicy"]["poly"]["review"]] if mode=="poly" else [registry["fusionPolicy"]["mono"]["windowsReview"]],
            "instrumentIds":list(dict.fromkeys(ids)),"family":family,"polyphonic":polyphonic,
            "minMidi":minimum,"maxMidi":maximum,
            "minHz":max(15,a4*2**((minimum-69)/12)/1.08),
            "maxHz":min(10000,a4*2**((maximum-69)/12)*1.08),"requiresConfirmation":[],"diagnostics":diagnostics}


def runtime_capabilities(home: Path):
    marker=home/"runtime-ready.json"
    if not marker.is_file():marker=home/"runtime-manifest.json"
    if not marker.is_file() or marker.stat().st_size>65536:
        return {engine:False for engine in ("basic-pitch","pyin","crepe")}
    try:
        metadata=json.loads(marker.read_text(encoding="utf8"))
        registry=home/"NoteWiseProfiles.json"
        if registry.is_file() and metadata.get("noteWiseRegistrySha256") and hashlib.sha256(registry.read_bytes()).hexdigest()!=metadata["noteWiseRegistrySha256"]:
            return {engine:False for engine in ("basic-pitch","pyin","crepe")}
        smoke=metadata.get("smoke",{})
        def passed(engine): return isinstance(smoke.get(engine),dict) and smoke[engine].get("passed") is True
        def verified(filename,key):
            model=home/"models"/filename
            return model.is_file() and hashlib.sha256(model.read_bytes()).hexdigest()==metadata.get(key)
        return {"pyin":passed("pyin") and (home/"mono_analysis.py").is_file(),
                "basic-pitch":passed("basic-pitch") and verified("basic-pitch.onnx","modelSha256"),
                "crepe":passed("crepe") and verified("crepe-tiny.onnx","crepeModelSha256")}
    except (OSError,ValueError,TypeError,AttributeError):
        return {engine:False for engine in ("basic-pitch","pyin","crepe")}


def valid_note(note):
    return (isinstance(note,dict) and isinstance(note.get("midi"),int) and not isinstance(note.get("midi"),bool)
            and 0<=note["midi"]<=127 and all(isinstance(note.get(k),(int,float)) and not isinstance(note.get(k),bool)
                and math.isfinite(note[k]) for k in ("onset","duration","confidence"))
            and note["onset"]>=0 and note["duration"]>0 and 0<=note["confidence"]<=1
            and ("cents" not in note or isinstance(note["cents"],(int,float)) and not isinstance(note["cents"],bool)
                 and math.isfinite(note["cents"]) and abs(note["cents"])<=100))


def detector_result(result,engine,seconds):
    if (not isinstance(result,dict) or result.get("schemaVersion")!=1 or result.get("engine")!=engine
            or not isinstance(result.get("notes"),list) or len(result["notes"])>20000):
        raise ValueError("Invalid actual NoteWise detector result: "+engine)
    previous=-1
    for note in result["notes"]:
        if not valid_note(note) or note["onset"]<previous or note["onset"]+note["duration"]>seconds+.001:
            raise ValueError("Invalid actual NoteWise acoustic note: "+engine)
        previous=note["onset"]
    return result


def note_frequency(note,a4):
    value=note.get("frequency")
    return value if isinstance(value,(int,float)) and math.isfinite(value) and value>0 else a4*2**((note["midi"]-69+note.get("cents",0)/100)/12)


def arbitrate_mono(primary,validator,validator_status,a4,threshold=.5,policy=None):
    """One-to-one attacks: a held validator note cannot confirm two re-attacks.

    Detector scores retain their own semantics. They are never averaged into a
    synthetic probability, and no score pitch is considered in these decisions.
    """
    policy=policy or profile_registry()["fusionPolicy"]["mono"]
    notes=copy.deepcopy(primary["notes"]);decisions=[];used=set();uncertainty=[]
    candidates=validator.get("notes",[]) if validator else []
    for index,note in enumerate(notes):
        frequency=note_frequency(note,a4)
        decision={"primaryIndex":index,"midi":note["midi"],"onset":note["onset"],"duration":note["duration"],
                  "primaryConfidence":note["confidence"],"frequency":frequency}
        if note["confidence"]<threshold or note.get("reviewRequired") or note.get("onsetReliable") is False:
            decision.update(status="review",reason="primary-evidence-uncertain")
        elif not CREPE_SAFE_MIN_HZ<=frequency<=CREPE_MAX_HZ:
            decision.update(status="primary-only",reason="outside-validator-safe-range")
        elif validator_status!="evaluated":
            decision.update(status="review",reason="validator-unavailable")
        else:
            eligible=[]
            for vi,other in enumerate(candidates):
                if vi in used or other["confidence"]<threshold or other.get("reviewRequired") or other.get("onsetReliable") is False:
                    continue
                difference=abs(other["onset"]-note["onset"])
                overlap=min(note["onset"]+note["duration"],other["onset"]+other["duration"])-max(note["onset"],other["onset"])
                if difference<=policy["onsetToleranceSeconds"] and overlap>=min(.04,min(note["duration"],other["duration"])*.25):
                    eligible.append((difference,vi,other))
            eligible.sort(key=lambda row:row[0])
            agreement=next((row for row in eligible if row[2]["midi"]==note["midi"]
                and abs(row[2].get("cents",0)-note.get("cents",0))<=policy["centsTolerance"]),None)
            if agreement:
                _,vi,other=agreement;used.add(vi)
                decision.update(status="agreement",reason="independent-pitch-and-attack-agreement",validatorIndex=vi,
                    validatorMidi=other["midi"],validatorConfidence=other["confidence"],validatorCents=other.get("cents"))
            else:
                decision.update(status="review",reason="detector-disagreement" if eligible else "validator-no-agreement")
                if eligible:
                    _,vi,other=eligible[0];used.add(vi)
                    decision.update(validatorIndex=vi,validatorMidi=other["midi"],validatorConfidence=other["confidence"])
        note["fusionDecision"]=copy.deepcopy(decision)
        if decision["status"]=="review":
            note.update(reviewRequired=True,reviewReason=decision["reason"],reason=decision["reason"])
            uncertainty.append({"onset":note["onset"],"duration":note["duration"],"reason":decision["reason"]})
        decisions.append(decision)
    # Audible strong validator attacks absent from the primary are evidence of
    # disagreement, not invented extra notes or expected-score corrections.
    for vi,other in enumerate(candidates):
        if vi not in used and other["confidence"]>=threshold and CREPE_SAFE_MIN_HZ<=note_frequency(other,a4)<=CREPE_MAX_HZ:
            uncertainty.append({"onset":other["onset"],"duration":other["duration"],"reason":"validator-only-acoustic-evidence"})
    return notes,decisions,uncertainty


def analyze_fusion(path,home,seconds,options,run_detector):
    a4=float(options.get("a4",440))
    plan=plan_recording(options.get("normalizedParts"),options.get("polyphonic"),a4,home)
    policy=profile_registry(home)["fusionPolicy"]
    capabilities=runtime_capabilities(home)
    if not capabilities.get(plan["primary"]):
        raise ValueError("The actual NoteWise primary detector is not installed or validated: "+plan["primary"])
    settings={"engine":plan["primary"],"a4":a4,"minHz":plan["minHz"],"maxHz":plan["maxHz"],
              "input":"recording","verified":True}
    # Only scalar instrument policy reaches detectors. No normalized score or
    # client-selected next pitch, expected timing or guessed notes are passed.
    primary=detector_result(run_detector(path,home,settings),plan["primary"],seconds)
    result=copy.deepcopy(primary);result["engine"]="notewise-fusion"
    result["rawNotes"]=copy.deepcopy(primary.get("rawNotes",primary["notes"]))
    warnings=list(primary.get("warnings",[]))+plan["diagnostics"];detectors={plan["primary"]:copy.deepcopy(primary)}
    decisions=[];validator_status="not-applicable";validation_warning=None
    if plan["mode"]=="mono":
        validator=None
        low=max(plan["minHz"],CREPE_SAFE_MIN_HZ);high=min(plan["maxHz"],CREPE_MAX_HZ)
        if low>=high:
            validator_status="outside-range"
        elif not capabilities.get("crepe"):
            validator_status="unavailable";validation_warning="CREPE independent review unavailable; eligible notes remain pending review."
        else:
            try:
                validator=detector_result(run_detector(path,home,{**settings,"engine":"crepe","minHz":low,"maxHz":high}),"crepe",seconds)
                detectors["crepe"]=copy.deepcopy(validator);validator_status="evaluated"
            except (OSError,ValueError,RuntimeError) as error:
                validator_status="failed";validation_warning="Independent CREPE review failed; eligible notes remain pending review: "+str(error)[:400]
        result["notes"],decisions,uncertainty=arbitrate_mono(primary,validator,validator_status,a4,policy=policy["mono"])
        result["uncertaintyIntervals"]=copy.deepcopy(primary.get("uncertaintyIntervals",[]))+uncertainty
        warnings.append("Below 50 Hz or above 1975.6 Hz, CREPE is not negative evidence; primary-only coverage is disclosed.")
    else:
        uncertainty=copy.deepcopy(primary.get("uncertaintyIntervals",[]))
        for i,note in enumerate(result["notes"]):
            proof=note.get("onsetEvidence",{})
            if note["confidence"]<policy["confidence"]["basicPitch"] or not isinstance(proof,dict) or proof.get("accepted") is not True:
                note.update(reviewRequired=True,reviewReason="independent-acoustic-attack-unconfirmed",reason="independent-acoustic-attack-unconfirmed")
            decision={"primaryIndex":i,"status":"review" if note.get("reviewRequired") else "primary-only",
                    "reason":note.get("reviewReason","actual-waveform-onset-qualification"),"midi":note["midi"],"onset":note["onset"]}
            note["fusionDecision"]=copy.deepcopy(decision);decisions.append(decision)
            if decision["status"]=="review":uncertainty.append({"onset":note["onset"],"duration":note["duration"],"reason":decision["reason"]})
        result["uncertaintyIntervals"]=uncertainty
        validator_status="waveform-evaluated"
        warnings.append("Polyphonic review uses actual Basic Pitch plus waveform onset qualification; no second polyphonic pitch model is claimed.")
    if validation_warning: warnings.append(validation_warning)
    result["warnings"]=list(dict.fromkeys(warnings))
    result["fusion"]={"policyVersion":POLICY_VERSION,"plan":plan,"detectors":detectors,"decisions":decisions,
        "validatorStatus":validator_status,"validatorWarning":validation_warning,
        "confidenceSemantics":"Original primary detector evidence; no cross-model probability averaging",
        "expectedScoreNotesUsedByDetectors":False}
    return result
