import { useEffect, useRef, useState } from "react";
import { account, type AccountIdentity, type Assignment, type CatalogScore, type Classroom, type PersonalScore, type Submission } from "./account";
import { errorMessage } from "./cloud";
import { ownedPracticeRecords, type PracticeHistoryState } from "./practice-summary";

type SharedScore = { id: string; title: string };
function sharedScores(course: Classroom | null): SharedScore[] {
  return Array.isArray(course?.sharedScores) ? course.sharedScores.filter((score): score is SharedScore => !!score && typeof score.id === "string" && typeof score.title === "string") : [];
}
function wrongNoteDescription(value: unknown): string {
  if (!value || typeof value !== "object") return "记录需复核";
  const error = value as { type?: string; measure?: number; expectedMidi?: number; playedMidi?: number; confidence?: number };
  const type = ({ wrong: "错音", missed: "漏音", extra: "多音", rhythm: "节奏", uncertain: "待复核" } as Record<string, string>)[error.type || ""] || "待复核";
  return `${error.measure === undefined ? "" : `第 ${error.measure} 小节 · `}${type}${error.expectedMidi === undefined ? "" : ` · 谱面音高 ${error.expectedMidi}`}${error.playedMidi === undefined ? "" : ` · 检测音高 ${error.playedMidi}`}${error.confidence === undefined ? "" : ` · 置信度 ${Math.round(error.confidence * 100)}%`}`;
}

export default function ClassroomSettings({ identity, history, image, outline, field, action, onScores }: { identity: AccountIdentity | null; history: PracticeHistoryState; image: string; outline: string; field: string; action: string; onScores: () => void }) {
  const [classCode, setClassCode] = useState(""), [createClassOpen, setCreateClassOpen] = useState(false), [classroomName, setClassroomName] = useState("");
  const [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
  const [courses, setCourses] = useState<Classroom[]>([]), [catalog, setCatalog] = useState<CatalogScore[]>([]), [scores, setScores] = useState<PersonalScore[]>([]);
  const [coursesLoaded, setCoursesLoaded] = useState(false), [submissionsLoaded, setSubmissionsLoaded] = useState(false);
  const [selectedCourse, setSelectedCourse] = useState<Classroom | null>(null), [assignments, setAssignments] = useState<Assignment[]>([]);
  const [preview, setPreview] = useState<{ code: string; info: Awaited<ReturnType<typeof account.previewCode>> } | null>(null);
  const [joinCode, setJoinCode] = useState<Awaited<ReturnType<typeof account.createCode>> | null>(null);
  const [source, setSource] = useState(""), [assignmentTitle, setAssignmentTitle] = useState(""), [assignmentScore, setAssignmentScore] = useState("");
  const [requirements, setRequirements] = useState(""), [dueAt, setDueAt] = useState("");
  const [selectedAssignment, setSelectedAssignment] = useState(""), [submissions, setSubmissions] = useState<Submission[]>([]);
  const [eventId, setEventId] = useState(""), [recording, setRecording] = useState<File | null>(null);
  const [audioURLs, setAudioURLs] = useState<Record<string, string>>({});
  const urls = useRef<string[]>([]), codeInputs = useRef<(HTMLInputElement | null)[]>([]), fileInput = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const records = ownedPracticeRecords(history, identity?.userId || null).filter((record) => record.sync === "synced");
  const teacher = selectedCourse?.role === "teacher";
  const button = `${action} disabled:cursor-default disabled:opacity-50`;
  useEffect(() => {
    const request = ++generation.current;
    setCourses([]); setCatalog([]); setScores([]); setSelectedCourse(null); setAssignments([]); setSubmissions([]); setPreview(null); setJoinCode(null); setAudioURLs({}); setEventId(""); setRecording(null); setMessage("");
    for (const url of urls.current) URL.revokeObjectURL(url); urls.current = [];
    if (identity) void Promise.all([account.courses(), account.catalog(), account.scores()]).then(([classes, official, personal]) => {
      if (generation.current === request && account.current?.userId === identity.userId) { setCourses(classes.courses); setCatalog(official.scores); setScores(personal.scores); setCoursesLoaded(true); }
    }).catch((error) => { if (generation.current === request) setMessage(errorMessage(error)); });
    return () => { generation.current++; for (const url of urls.current) URL.revokeObjectURL(url); urls.current = []; };
  }, [identity?.userId]);

  async function perform(task: (current: () => boolean) => Promise<void>) {
    if (busy || !identity) return;
    const request = generation.current, owner = identity.userId;
    const current = () => generation.current === request && account.current?.userId === owner;
    setBusy(true); setMessage("");
    try { await task(current); } catch (error) { if (current()) setMessage(errorMessage(error)); }
    finally { if (generation.current === request) setBusy(false); }
  }
  async function refreshCourse(courseId: string, current: () => boolean) {
    const [course, work] = await Promise.all([account.course(courseId), account.assignments(courseId)]);
    if (current()) { setSelectedCourse(course); setAssignments(work.assignments); setCourses((previous) => [course, ...previous.filter((item) => item.id !== course.id)]); }
  }
  function updateCode(value: string) { setClassCode(value); setPreview(null); setMessage(""); }
  async function readSubmissions(assignmentId: string, current: () => boolean) {
    const result = await account.submissions(assignmentId);
    if (current()) { setSelectedAssignment(assignmentId); setSubmissions(result.submissions); setSubmissionsLoaded(true); }
  }
  return <div>
    <div className="flex h-48 items-center justify-center overflow-hidden bg-[#67db23]"><img src={image} alt="黑白键练琴小猫" className="h-44 w-44 object-contain" /></div>
    <div className="px-4 py-7">
      {!identity && <p role="status" className="mb-5 text-[13px] leading-6 text-[#999]">请先在个人档案登录账户，再创建或加入课堂。</p>}
      <section aria-labelledby="create-class-title" className={`mb-7 border-b-2 pb-7 ${outline}`}>
        <h2 id="create-class-title" className="text-[24px] font-bold">创建课堂</h2>
        <p className="mt-4 text-[15px] leading-7 text-[#999]">创建你的专属练琴课堂，邀请学生加入，统一安排练习并查看学习进度。</p>
        {!createClassOpen ? <button type="button" disabled={busy || !identity} onClick={() => setCreateClassOpen(true)} className={`${button} mt-5 flex items-center justify-center text-center`}>创建课堂</button> : <form className="mt-5" onSubmit={(event) => {
          event.preventDefault(); void perform(async (current) => { const course = await account.createCourse(classroomName.trim()); if (current()) { setCourses((previous) => [course, ...previous]); setSelectedCourse(course); setAssignments([]); setCreateClassOpen(false); setClassroomName(""); setMessage(`课堂「${course.title}」已创建。`); } });
        }}>
          <label className="block text-[17px] font-bold">课堂名称<input autoFocus required maxLength={40} disabled={busy} value={classroomName} onChange={(event) => setClassroomName(event.currentTarget.value)} placeholder="例如：周六钢琴基础班" className={field} /></label>
          <div className="mt-4 flex gap-3"><button type="button" disabled={busy} onClick={() => setCreateClassOpen(false)} className={`${button} flex-1 text-[#999]`}>取消</button><button type="submit" disabled={busy || !classroomName.trim()} className="h-12 flex-1 cursor-pointer rounded-[14px] bg-[#67db23] text-[16px] font-bold text-white disabled:cursor-default disabled:bg-[#e5e5e5] disabled:text-[#aaa]">确认创建</button></div>
        </form>}
      </section>
      <h2 className="text-[24px] font-bold">加入课堂</h2><p className="mt-4 text-[15px] leading-7 text-[#999]">请输入老师发给你的课堂代码。先确认教师和分享范围，再加入课堂。</p>
      <div className="mt-5 grid grid-cols-6 gap-2" role="group" aria-label="六位课堂代码">
        {Array.from({ length: 6 }, (_, index) => <input key={index} ref={(element) => { codeInputs.current[index] = element; }} aria-label={`课堂代码第${index + 1}位`} value={classCode[index]?.trim() || ""} disabled={busy || !identity} maxLength={1} autoCapitalize="characters" autoComplete="off" onChange={(event) => {
          const character = event.currentTarget.value.replace(/[^a-zA-Z0-9]/g, "").toUpperCase().slice(-1);
          updateCode(classCode.padEnd(6, " ").slice(0, index) + (character || " ") + classCode.padEnd(6, " ").slice(index + 1));
          if (character && index < 5) codeInputs.current[index + 1]?.focus();
        }} onKeyDown={(event) => { if (event.key === "Backspace" && !classCode[index]?.trim() && index > 0) codeInputs.current[index - 1]?.focus(); }} onPaste={(event) => {
          event.preventDefault(); const pasted = event.clipboardData.getData("text").replace(/[^a-zA-Z0-9]/g, "").toUpperCase().slice(0, 6); updateCode(pasted); codeInputs.current[Math.min(pasted.length, 5)]?.focus();
        }} className={`${field} h-14 px-0 text-center text-[22px]`} />)}
      </div>
      <button type="button" disabled={busy || !identity || !/^[A-Z0-9]{6}$/.test(classCode)} onClick={() => void perform(async (current) => { const code = classCode, info = await account.previewCode(code); if (current()) setPreview({ code, info }); })} className="mt-5 h-12 w-full cursor-pointer rounded-[14px] bg-[#67db23] text-[17px] font-bold text-white disabled:cursor-default disabled:bg-[#e5e5e5] disabled:text-[#aaa]">提交</button>
      {preview && preview.code === classCode && <section className={`mt-5 rounded-[18px] border-2 p-4 ${outline}`}><h3 className="text-[19px] font-bold">{preview.info.title}</h3><p className="mt-3 text-[15px] leading-7 text-[#999]">教师：{preview.info.teacher}<br />{preview.info.sharingScope}</p><button type="button" disabled={busy} className={`${button} mt-4`} onClick={() => void perform(async (current) => { const course = await account.joinCode(preview.code); if (current()) { setCourses((previous) => [course, ...previous.filter((item) => item.id !== course.id)]); setPreview(null); setMessage("已加入课堂。课堂练习谱已加入我的曲谱；个人练习历史不会自动分享。"); await refreshCourse(course.id, current); } })}>确认分享范围并加入</button></section>}
      <p role="status" className="mt-4 text-[13px] leading-6 text-[#999]">{busy ? "正在处理…" : message}</p>
      {identity && <details className={`mt-7 rounded-[18px] border-2 p-4 ${outline}`} open={!!selectedCourse}>
        <summary className="cursor-pointer text-[20px] font-bold">我的课堂</summary>
        <button type="button" disabled={busy} className={`${button} mt-4`} onClick={() => void perform(async (current) => { const result = await account.courses(); if (current()) { setCourses(result.courses); setCoursesLoaded(true); } })}>刷新课堂</button>
        {!courses.length && <p className="mt-4 text-[15px] text-[#999]">{coursesLoaded ? "暂未创建或加入课堂。" : "课堂列表尚未载入，请刷新。"}</p>}
        {courses.map((course) => <button type="button" key={course.id} disabled={busy} className={`${button} mt-3 text-left`} onClick={() => void perform(async (current) => { setSubmissions([]); setSelectedAssignment(""); setJoinCode(null); setAssignmentScore(""); await refreshCourse(course.id, current); })}>{course.title} · {course.role === "teacher" ? "教师" : "学生"}</button>)}
        {selectedCourse && <>
          <h3 className="mt-5 text-[19px] font-bold">{selectedCourse.title}</h3><p className="mt-2 text-[13px] leading-6 text-[#999]">教师：{selectedCourse.teacher || identity.username}<br />{typeof selectedCourse.sharingScope === "string" ? selectedCourse.sharingScope : "只分享本课堂已提交作业。"}<br />{teacher ? "仅当前课堂教师可查看学生提交。" : "你只能查看自己的提交。"}</p>
          <button type="button" className={`${button} mt-3`} onClick={onScores}>到我的曲谱练习课堂曲谱</button>
          {teacher && <>
            <button type="button" disabled={busy} className={`${button} mt-4`} onClick={() => void perform(async (current) => { const result = await account.createCode(selectedCourse.id); if (current()) setJoinCode(result); })}>生成限时课堂代码</button>
            {joinCode && <p role="status" className="mt-3 text-[15px] leading-7 text-[#999]">课堂代码：<strong className="text-[22px]">{joinCode.code}</strong><br />有效至 {new Date(joinCode.expiresAt).toLocaleString()}</p>}
            <details className="mt-5"><summary className="cursor-pointer text-[17px] font-bold">分享练习曲谱</summary>
              <label className="mt-3 block text-[17px] font-bold">曲谱<select aria-label="课堂分享曲谱" disabled={busy} value={source} onChange={(event) => setSource(event.currentTarget.value)} className={field}><option value="">选择官方或个人曲谱</option><optgroup label="官方曲谱">{catalog.map((score) => <option key={score.id} value={`official:${score.id}`}>{score.title}</option>)}</optgroup><optgroup label="我的曲谱">{scores.map((score) => <option key={score.id} value={`personal:${score.id}`}>{score.title}</option>)}</optgroup></select></label>
              <button type="button" disabled={busy || !source} className={`${button} mt-3`} onClick={() => void perform(async (current) => { const [kind, scoreId] = source.split(":"); await account.addCourseScore(selectedCourse.id, kind as "official" | "personal", scoreId); if (current()) { await refreshCourse(selectedCourse.id, current); setMessage("曲谱已加入课堂。学生重新同步课堂后可领取。"); } })}>加入课堂曲谱</button>
            </details>
            <details className="mt-5"><summary className="cursor-pointer text-[17px] font-bold">布置练习作业</summary>
              <form onSubmit={(event) => { event.preventDefault(); void perform(async (current) => { await account.createAssignment(selectedCourse.id, { title: assignmentTitle.trim(), courseScoreId: assignmentScore, ...(dueAt ? { dueAt: new Date(dueAt).toISOString() } : {}), ...(requirements.trim() ? { requirements: requirements.trim() } : {}) }); if (current()) { setAssignmentTitle(""); await refreshCourse(selectedCourse.id, current); setMessage("作业已布置。"); } }); }}>
                <label className="mt-3 block text-[17px] font-bold">作业名称<input aria-label="作业名称" required maxLength={200} disabled={busy} value={assignmentTitle} onChange={(event) => setAssignmentTitle(event.currentTarget.value)} className={field} /></label>
                <label className="mt-3 block text-[17px] font-bold">课堂曲谱<select aria-label="作业曲谱" required disabled={busy} value={assignmentScore} onChange={(event) => setAssignmentScore(event.currentTarget.value)} className={field}><option value="">选择已分享曲谱</option>{sharedScores(selectedCourse).map((score) => <option key={score.id} value={score.id}>{score.title}</option>)}</select></label>
                <label className="mt-3 block text-[17px] font-bold">截止时间<input aria-label="作业截止时间" type="datetime-local" disabled={busy} value={dueAt} onChange={(event) => setDueAt(event.currentTarget.value)} className={field} /></label>
                <label className="mt-3 block text-[17px] font-bold">练习要求<textarea aria-label="作业要求" maxLength={2000} disabled={busy} value={requirements} onChange={(event) => setRequirements(event.currentTarget.value)} className={`${field} min-h-24 py-3`} /></label>
                <button type="submit" disabled={busy || !assignmentTitle.trim() || !assignmentScore} className={`${button} mt-3`}>布置作业</button>
              </form>
            </details>
          </>}
          <section className="mt-6"><h3 className="text-[19px] font-bold">课堂作业</h3>{!assignments.length && <p className="mt-3 text-[15px] text-[#999]">暂无作业。</p>}{assignments.map((assignment) => <div key={assignment.id} className={`mt-4 border-t-2 pt-4 ${outline}`}><h4 className="text-[17px] font-bold">{assignment.title}</h4><p className="mt-2 text-[13px] leading-6 text-[#999]">{assignment.requirements || "未填写额外要求"}<br />{assignment.dueAt ? `截止：${new Date(assignment.dueAt).toLocaleString()}` : "不设截止时间"}</p><button type="button" disabled={busy} className={`${button} mt-3`} onClick={() => void perform(async (current) => { setEventId(""); setRecording(null); setSubmissions([]); setSubmissionsLoaded(false); setSelectedAssignment(assignment.id); if (fileInput.current) fileInput.current.value = ""; await readSubmissions(assignment.id, current); })}>{teacher ? "查看学生提交" : "提交作业 / 查看我的提交"}</button></div>)}</section>
          {selectedAssignment && <section className={`mt-5 border-t-2 pt-4 ${outline}`}><h3 className="text-[19px] font-bold">{teacher ? "学生提交" : "我的作业提交"}</h3>
            {!teacher && <form onSubmit={(event) => { event.preventDefault(); void perform(async (current) => { let uploadId: string | undefined; if (recording) uploadId = await account.uploadRecording(selectedAssignment, recording); if (!current()) return; await account.submit(selectedAssignment, eventId, uploadId); if (current()) { await readSubmissions(selectedAssignment, current); setRecording(null); if (fileInput.current) fileInput.current.value = ""; setMessage("作业已提交。未听音分析的记录保留未分析状态。"); } }); }}>
              <label className="mt-3 block text-[17px] font-bold">练习记录<select aria-label="作业练习记录" required disabled={busy} value={eventId} onChange={(event) => setEventId(event.currentTarget.value)} className={field}><option value="">选择自己已保存并同步的作业练习</option>{records.map((record) => <option key={record.eventId} value={record.eventId}>{record.name} · {new Date(record.startedAt).toLocaleString()} · {Math.round(record.durationSeconds)}秒</option>)}</select></label>
              <p className="mt-2 text-[12px] leading-6 text-[#999]">请先在我的曲谱练习课堂领取的曲谱。服务会核对记录与作业曲谱；试听记录不表示音准分析。</p>
              <label className="mt-3 block text-[17px] font-bold">演奏录音（可选）<input ref={fileInput} aria-label="作业录音文件" type="file" accept=".wav,.mp3,.ogg,.m4a,audio/wav,audio/mpeg,audio/ogg,audio/mp4" disabled={busy} onChange={(event) => { const file = event.currentTarget.files?.[0] || null; setRecording(file); }} className={field} /></label>
              <p className="mt-2 text-[12px] leading-6 text-[#999]">仅上传你选择的真实录音文件，支持 WAV、MP3、Ogg、M4A，最多 100 MB。提交后仅本课堂教师可查看。</p>
              <button type="submit" disabled={busy || !eventId} className={`${button} mt-3`}>确认提交练习与选定录音</button>
            </form>}
            {!submissions.length && <p className="mt-3 text-[15px] text-[#999]">{submissionsLoaded ? "暂无提交记录。" : "提交列表尚未载入，请重新读取。"}</p>}
            {submissions.map((submission) => <details key={submission.id} className={`mt-4 border-t-2 pt-4 ${outline}`}><summary className="cursor-pointer text-[17px] font-bold">{submission.student} · {new Date(submission.submittedAt).toLocaleString()}{submission.late ? " · 逾期" : ""}</summary><p className="mt-3 text-[13px] leading-6 text-[#999]">实际保存时长：{Math.round(submission.event.durationSeconds)} 秒 · {submission.event.mode === "playback" ? "谱面试听" : submission.event.mode === "free" ? "自由练习" : submission.event.mode === "strict" ? "严格节拍" : "跟谱"}<br />{submission.analysis.errors === null ? "尚未分析错音。" : `检测记录：${submission.analysis.errors.length} 项；${submission.analysis.verifiedByServer ? "已服务端复核" : "客户端报告，尚未服务端复核"}。`}</p>{submission.analysis.errors && <ul className="mt-3 text-[13px] leading-6 text-[#999]">{submission.analysis.errors.map((error, index) => <li key={index}>{wrongNoteDescription(error)}</li>)}</ul>}
              {submission.audioAvailable ? <><button type="button" disabled={busy} className={`${button} mt-3`} onClick={() => void perform(async (current) => { if (await account.playAudio(submission.id)) { if (current()) setMessage("作业录音已在播放器打开。"); return; } if (!current()) return; const blob = await account.audio(submission.id); if (current()) { const url = URL.createObjectURL(blob); urls.current.push(url); setAudioURLs((previous) => ({ ...previous, [submission.id]: url })); } })}>载入作业录音</button>{audioURLs[submission.id] && <audio aria-label={`${submission.student}的作业录音`} controls preload="metadata" src={audioURLs[submission.id]} className="mt-3 w-full" />}</> : <p className="mt-3 text-[13px] text-[#999]">未附录音。</p>}
            </details>)}
          </section>}
        </>}
      </details>}
    </div>
  </div>;
}
