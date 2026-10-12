import { useEffect, useState } from "react";
import { installedLegalInformation, LEGAL_RESEARCH_URL, type LegalInformation } from "./legal-information.ts";

export default function PrivacyDetails(){
  const [legal, setLegal] = useState<LegalInformation | null>(null);
  const [legalError, setLegalError] = useState(false);
  useEffect(() => {
    let active = true;
    installedLegalInformation().then((value) => { if (active) setLegal(value); }).catch(() => { if (active) setLegalError(true); });
    return () => { active = false; };
  }, []);
  return <div className="px-5 py-6 text-[14px] leading-7 text-[#999]">
  <p className="mb-4">隐私政策 · 2026 年 10 月 12 日</p>
  <h2 className="text-[17px] font-bold">曲谱与账户</h2><p className="mb-5">登录后主动导入识谱时，选定的 PDF、图片和文件名发送到黑白键官方 HTTPS 识谱服务。注册与登录使用用户名、密码和设备名称；服务器保存密码校验值。登录后，个人曲谱快照、练习计时和分析版本同步到当前账户；未登录记录仅保存在本机，不会自动迁入其他账户。</p>
  <h2 className="text-[17px] font-bold">个人设置</h2><p className="mb-5">登录后的姓名、头像、联系资料、乐器课程、外观和提醒开关按账户保存与同步。邮箱、电话为未经验证的联系资料，不用于登录。离线修改先保存在该账户的本机待同步队列，联网后重试；页面会标明同步状态。访客及旧版未标明归属的设置不会自动复制到另一账户。个人数据导出不含密码、登录凭据或录音文件，也不代替服务器备份。</p>
  <h2 className="text-[17px] font-bold">听音与录音</h2><p className="mb-5">选择麦克风并点击开始练习后才请求系统权限，声音在设备上分析并保存为本机演奏录音。暂停、结束、离开页面或进入后台时停止采音。录音不会自动上传；MIDI 也在本机处理。</p>
  <h2 className="text-[17px] font-bold">课堂分享</h2><p className="mb-5">加入课堂不会自动分享个人练习历史。只有确认提交作业后，该课堂教师才可查看选定的练习记录、固定分析版本和你明确勾选或选择的录音。后来追加的分析不会自动改写已提交作业。</p>
  <h2 className="text-[17px] font-bold">AI 分析</h2><p className="mb-5">点击分析后，服务从所选练习记录生成汇总事实，发送给 DeepSeek 生成说明。不向模型发送原始录音、乐谱 XML、逐音数组、密码或令牌。缺少演奏依据、未判断或待复核的项目不会算作正确。没有记录时不能分析。</p>
  <h2 className="text-[17px] font-bold">保留与退出</h2><p className="mb-5">退出登录清除当前设备的登录凭据并隐藏私人内容，服务器上的账户资料继续保留。你可在个人档案中永久注销账户；确认后，账户、全部登录会话、个人曲谱、练习记录、分析和录音会删除，你创建的课堂与作业会关闭。其他用户已领取的个人曲谱副本和他们自己的练习记录会保留。永久注销无法恢复。</p>
  <p>无广告追踪、跨应用追踪或出售用户数据。隐私联系：Lucas.z0623@outlook.com。</p>
  <h2 className="mt-5 text-[17px] font-bold">软件许可与对应源码</h2>
  <p className="mb-3">应用保留所用开源组件的原始许可、版权和修改说明。以下资料为公开软件信息，查看无需登录。</p>
  {legal ? <>
    <p>当前安装包源码版本：</p><code className="block break-all text-[12px]">{legal.sourceCommit}</code>
    <a className="block mb-3 underline" href={legal.sourceArchiveURL} target="_blank" rel="noopener noreferrer">下载此版本对应源码</a>
    <details className="mb-3"><summary>查看完整软件许可</summary><pre className="mt-2 whitespace-pre-wrap break-words text-[12px] leading-5">{legal.license}</pre></details>
    <details className="mb-3"><summary>查看版权、来源与修改说明</summary><pre className="mt-2 whitespace-pre-wrap break-words text-[12px] leading-5">{legal.notice}</pre></details>
  </> : <p className="mb-3">{legalError ? "当前安装包许可资料暂不可读取，可先查看公开研究说明。" : "浏览器预览可查看公开研究说明；安装包提供此版本的完整许可与对应源码。"}</p>}
  <a className="underline" href={LEGAL_RESEARCH_URL} target="_blank" rel="noopener noreferrer">查看引擎研究与许可边界</a>
</div>}
