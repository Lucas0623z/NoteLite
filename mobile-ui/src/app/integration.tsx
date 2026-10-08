import { useEffect, useRef, useState } from "react";
import { summarizeHistory, useYinban, type ScoreRecord } from "./runtime";
import Modal from "./Modal";

const button = "min-h-11 cursor-pointer rounded-[13px] border-2 border-b-[5px] border-[#e5e5e5] px-3 text-[14px] font-bold text-[#67db23] active:translate-y-[3px] active:border-b-2 disabled:opacity-50";
const phases: Record<string, string> = { imported: "待识谱", uploading: "上传中", queued: "排队中", running: "云端识谱中", downloading: "正在保存识谱结果", succeeded: "识谱完成", failed: "识谱失败", cancelled: "已取消", canceled: "已取消" };

export function ConnectedScoresPage({ isDark, normalImage, pressedImage }: { isDark: boolean; normalImage: string; pressedImage: string }) {
  const { state, native, send, importPreview } = useYinban();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [importLanding, setImportLanding] = useState(false);
  const existingIDs = useRef(new Set<string>());
  const hero = importLanding || state.records.length === 0;
  useEffect(() => { if (importLanding && state.records.some(record => !existingIDs.current.has(record.id))) setImportLanding(false); }, [state.records, importLanding]);
  const [edit, setEdit] = useState<{ record: ScoreRecord; action: "rename" | "delete" } | null>(null);
  const [title, setTitle] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const choose = (action: string, target: HTMLInputElement | null) => { setUploadOpen(false); native ? send(action) : target?.click(); };
  const onImport = async (event: React.ChangeEvent<HTMLInputElement>) => { if (event.currentTarget.files) { const imported = await importPreview(event.currentTarget.files); if (imported > 0) setImportLanding(false); } event.target.value = ""; };
  const surface = isDark ? "border-white/15 bg-[#252525] text-white" : "border-[#e5e5e5] bg-white text-[#4b4b4b]";
  return <section data-mode={hero ? "import" : "library"} className={`relative flex min-h-full flex-col px-4 ${hero ? "items-center justify-center py-8" : "py-5"}`}>
    <input ref={input} type="file" multiple accept="image/*,.pdf,.musicxml,.mxl,.xml" aria-label="选择曲谱文件或图片" className="hidden" onChange={event => void onImport(event)} />
    <input ref={imageInput} type="file" multiple accept="image/*" aria-label="从相册选择曲谱" className="hidden" onChange={event => void onImport(event)} />
    <input ref={cameraInput} type="file" accept="image/*" capture="environment" aria-label="拍摄曲谱" className="hidden" onChange={event => void onImport(event)} />
    {importLanding && state.records.length > 0 && <button aria-label="返回我的曲谱" onClick={() => setImportLanding(false)} className="absolute top-3 left-4 min-h-11 px-2 text-sm font-bold text-[#999]">‹ 返回我的曲谱</button>}
    {hero ? <button type="button" disabled={!state.canImport} aria-label="上传文件、图片或拍照识谱，开启你的专属陪练" onClick={() => setUploadOpen(true)} className="group relative block w-full max-w-[400px] cursor-pointer touch-manipulation rounded-[18px] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#67db23]">
      <img src={normalImage} alt="作曲家们陪你练琴：上传文件、图片或拍照识谱，开启你的专属陪练吧！" draggable={false} className="block h-auto w-full select-none group-active:opacity-0" />
      <img src={pressedImage} alt="" aria-hidden="true" draggable={false} className="pointer-events-none absolute inset-0 h-full w-full select-none object-contain opacity-0 group-active:opacity-100" />
    </button> : <div className="mb-5 flex items-center justify-between gap-2"><h1 className="text-[23px] font-bold">我的曲谱</h1><button aria-label="导入乐谱" disabled={!state.canImport} onClick={() => { existingIDs.current = new Set(state.records.map(record => record.id)); setImportLanding(true); }} className={button}>导入乐谱</button></div>}
    {!hero && <div className="space-y-4">{state.records.map(record => {
      const active = state.activeIDs.includes(record.id);
      const progress = record.phase === "uploading" && typeof record.progress === "number" ? Math.max(0, Math.min(100, record.progress > 1 ? record.progress : record.progress * 100)) : null;
      return <article key={record.id} role="group" aria-label={`曲谱 ${record.title}`} className={`rounded-[18px] border-2 border-b-[5px] p-4 ${surface}`}>
        <h2 className="break-words text-[19px] font-bold">{record.title}</h2>
        <p className="mt-2 text-[13px] text-[#999]">{record.canPractice ? `${record.partCount || 1} 个练习乐谱` : record.paused ? "已暂停" : phases[record.phase] || record.phase} · {record.kind.toUpperCase()}</p>
        {active && <div className="mt-3"><div role="progressbar" aria-label={`${record.title}识谱进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress ?? undefined} className="h-3 overflow-hidden rounded-full bg-[#e5e5e5]"><div className="h-full rounded-full bg-[#67db23]" style={{ width: progress === null ? "35%" : `${progress}%` }} /></div><p role="status" className="mt-2 text-xs text-[#999]">{phases[record.phase] || "正在处理"}{progress !== null ? ` · ${Math.round(progress)}%` : ""}</p></div>}
        {record.error && <p role="alert" className="mt-3 break-words text-[13px] leading-6 text-[#d74b4b]">{record.error}</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          {record.canPractice ? <button aria-label={`开始练习 ${record.title}`} onClick={() => send("practice", { id: record.id })} className={`${button} border-[#48aa16] bg-[#67db23] text-white`}>开始练习</button> : active ? <button onClick={() => send("pause", { id: record.id })} className={button}>暂停识谱</button> : <button onClick={() => send(state.serverConfigured ? "recognize" : "serverSettings", { id: record.id })} className={button}>{state.serverConfigured ? record.error || record.paused ? "重试识谱" : "云端识谱" : "配置云端识谱"}</button>}
          <button onClick={() => send("preview", { id: record.id })} className={button}>查看曲谱</button>
          <button onClick={() => { setTitle(record.title); setEdit({ record, action: "rename" }); }} className={button}>重命名</button>
          <button onClick={() => setEdit({ record, action: "delete" })} className={`${button} text-[#d74b4b]`}>删除</button>
        </div>
      </article>;
    })}<button onClick={() => send("serverSettings")} className={`${button} w-full`}>云端识谱设置</button><button onClick={() => send("demo")} className={`${button} w-full`}>载入示例曲谱</button></div>}
    {state.error && <p role="alert" className="mt-4 text-sm text-[#d74b4b]">{state.error}</p>}
    {uploadOpen && <Modal label="导入曲谱方式" onDismiss={() => setUploadOpen(false)} className="upload-menu-overlay fixed inset-0 z-50 flex items-end justify-center bg-black/45 p-4 pb-[max(16px,env(safe-area-inset-bottom))]"><div className={`upload-menu-panel max-h-[calc(100dvh-32px)] w-full max-w-[520px] overflow-y-auto rounded-[20px] border-2 p-5 ${surface}`}><h2 className="mb-2 text-xl font-bold">导入曲谱</h2><p className="mb-4 text-sm leading-6 text-[#999]">图片和 PDF 发送至你配置的云端 OMR 服务识谱；声音识别在本机处理。</p><div className="space-y-3"><button onClick={() => choose("importFiles", input.current)} className={`${button} w-full`}>选择文件</button><button onClick={() => choose("importPhotos", imageInput.current)} className={`${button} w-full`}>从相册选择</button><button onClick={() => choose("capturePhoto", cameraInput.current)} className={`${button} w-full`}>拍照识谱</button><button onClick={() => { setUploadOpen(false); setImportLanding(false); send("demo"); }} className={`${button} w-full`}>载入示例曲谱</button><button onClick={() => setUploadOpen(false)} className={`${button} w-full text-[#999]`}>取消</button></div></div></Modal>}
    {edit && <Modal alert label={edit.action === "delete" ? "确认删除曲谱" : "重命名曲谱"} onDismiss={() => setEdit(null)} className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-5"><form onSubmit={event => { event.preventDefault(); send(edit.action, { id: edit.record.id, title: title.trim() }); setEdit(null); }} className={`w-full max-w-sm rounded-[20px] border-2 p-5 ${surface}`}>
      <h2 className="text-xl font-bold">{edit.action === "delete" ? "删除这份曲谱？" : "重命名曲谱"}</h2>
      {edit.action === "delete" ? <p className="my-4 break-words text-sm leading-7">将删除「{edit.record.title}」及本机识谱文件。练习记录保留。</p> : <input autoFocus required maxLength={100} aria-label="曲谱名称" value={title} onChange={event => setTitle(event.target.value)} className={`my-5 min-h-12 w-full rounded-xl border-2 p-3 ${surface}`} />}
      <div className="mt-3 flex gap-3"><button type="button" onClick={() => setEdit(null)} className={`${button} flex-1`}>取消</button><button type="submit" disabled={edit.action === "rename" && !title.trim()} className={`${button} flex-1 ${edit.action === "delete" ? "text-[#d74b4b]" : ""}`}>{edit.action === "delete" ? "确认删除" : "保存名称"}</button></div>
    </form></Modal>}
  </section>;
}

export function ConnectedHistoryPage({ isDark, openCalendar }: { isDark: boolean; openCalendar: () => void }) {
  const { state, native, send } = useYinban();
  const [selected, setSelected] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const stats = summarizeHistory(state.history);
  const surface = isDark ? "border-white/15 bg-[#252525]" : "border-[#e5e5e5] bg-white";
  const detail = state.history.find(item => item.id === selected);
  return <section className="px-4 py-5"><div className="mb-4 flex items-center justify-between"><h1 className="text-[23px] font-bold">练习记录</h1><button onClick={openCalendar} className={button}>练琴日历</button></div>
    <div className={`mb-5 grid grid-cols-3 rounded-[18px] border-2 p-4 text-center ${surface}`}>{[{ value: stats.sessions, label: "次练习" }, { value: stats.minutes, label: "分钟" }, { value: stats.accuracy === null ? "—" : `${stats.accuracy}%`, label: "首次正确率" }].map(item => <div key={item.label}><p className="text-[22px] font-bold">{item.value}</p><p className="mt-1 text-xs text-[#999]">{item.label}</p></div>)}</div>
    {!state.history.length ? <div className="py-14 text-center"><p className="text-[18px] font-bold">还没有练习记录</p><p className="mt-3 text-sm leading-7 text-[#999]">导入 MusicXML，或载入示例曲谱开始练习。结束后自动保存在本机。</p></div> : <div className="space-y-3">{state.history.map(item => <article key={item.id} className={`rounded-[18px] border-2 p-4 ${surface}`}><button onClick={() => native ? send("historyDetail", { id: item.id }) : setSelected(item.id)} className="block w-full text-left"><h2 className="break-words text-[18px] font-bold">{item.title}</h2><p className="mt-2 text-xs leading-6 text-[#999]">{new Date(item.startedAt).toLocaleString("zh-CN")} · {Math.floor(item.durationSeconds / 60)} 分 {Math.floor(item.durationSeconds % 60)} 秒</p><p className="mt-1 text-sm">{item.completed ? "已完成" : "未完成"} · {item.errors.length} 处问题记录</p></button><button onClick={() => setRemoving(item.id)} className="mt-3 min-h-11 text-sm font-bold text-[#d74b4b]">删除记录</button></article>)}<button onClick={() => setRemoving("all")} className={`${button} w-full text-[#d74b4b]`}>清空练习记录</button></div>}
    {detail && <Modal label="练习记录详情" onDismiss={() => setSelected(null)} className="fixed inset-0 z-50 overflow-y-auto bg-black/45 p-5"><div className={`mx-auto mt-12 max-w-lg rounded-[20px] border-2 p-5 ${surface}`}><h2 className="text-xl font-bold">{detail.title}</h2><p className="mt-3 text-sm leading-7">{detail.completed ? "已完成这次练习" : "本次未完成，未演奏的部分没有评分。"}</p>{detail.total ? <p className="mt-2 text-sm">首次弹对 {detail.firstTryCorrect ?? 0} / {detail.total}</p> : null}{detail.errors.length ? <ol className="mt-4 space-y-3">{detail.errors.map((error, index) => <li key={index} className="rounded-xl border p-3 text-sm">{issueText(error)}</li>)}</ol> : <p className="my-4 text-sm text-[#999]">未记录错音。未完成的部分不计入正确率。</p>}<button onClick={() => setSelected(null)} className={`${button} mt-5 w-full`}>关闭详情</button></div></Modal>}
    {removing && <Modal alert label="确认删除练习记录" onDismiss={() => setRemoving(null)} className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-5"><div className={`max-w-sm rounded-[20px] border-2 p-5 ${surface}`}><h2 className="text-xl font-bold">{removing === "all" ? "清空全部练习记录？" : "删除这条练习记录？"}</h2><p className="my-4 text-sm text-[#999]">删除后无法恢复，日历和成长进度会重新计算。</p><div className="flex gap-3"><button onClick={() => setRemoving(null)} className={`${button} flex-1`}>取消</button><button onClick={() => { send(removing === "all" ? "clearHistory" : "deleteHistory", { id: removing }); setRemoving(null); }} className={`${button} flex-1 text-[#d74b4b]`}>确认删除</button></div></div></Modal>}
  </section>;
}
function issueText(error: unknown) {
  const item = (error && typeof error === "object" ? error : {}) as Record<string, unknown>;
  const names: Record<string, string> = { wrong: "错音", missing: "漏音", early: "提前", late: "延后", extra: "多弹", intonation: "音准偏差" };
  const expected = Array.isArray(item.expected) ? item.expected.map(note => midiName(Number(note))).join(" + ") : "";
  return `第 ${item.measure ?? "—"} 小节 · ${names[String(item.kind)] || "演奏问题"}${expected ? ` · 应弹 ${expected}` : ""}${typeof item.played === "number" ? ` · 听到 ${midiName(item.played)}` : ""}${typeof item.cents === "number" ? ` · ${Math.round(item.cents)} 音分` : ""}`;
}
function midiName(note: number) { return ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"][((note % 12) + 12) % 12] + (Math.floor(note / 12) - 1); }
