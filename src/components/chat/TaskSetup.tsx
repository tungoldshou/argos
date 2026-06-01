// TaskSetup.tsx — 任务高级设置(验证命令/项目目录/监控测试文件)。
// 会话开始前可改、收进可折叠区;开始后由 AgentPanel 折叠为只读摘要。
import { useState } from 'react';
import { Icon } from '../../lib/icons';

interface TaskSetupProps {
  verifyCmd: string;
  projectDir: string;
  guardFiles: string;
  onChange: (patch: Partial<{ verifyCmd: string; projectDir: string; guardFiles: string }>) => void;
}

const inputStyle: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', height: 32, padding: '0 11px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))',
  color: 'var(--text-2)', fontSize: 12, fontFamily: 'var(--mono)',
};

export function TaskSetup({ verifyCmd, projectDir, guardFiles, onChange }: TaskSetupProps) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginBottom: 10 }}>
      <button onClick={() => setOpen((v) => !v)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)', fontFamily: 'var(--mono)', fontSize: 11.5 }}>
        <Icon name="layers" size={12} /> 高级设置（验证命令 / 项目目录）
        <Icon name="chevron" size={11} style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }} />
      </button>
      {open && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <input value={verifyCmd} onChange={(e) => onChange({ verifyCmd: e.target.value })}
            placeholder='验证命令(可选,如 python3 check.py)— 给了它,"完成"必须过验证' style={inputStyle} />
          <input value={projectDir} onChange={(e) => onChange({ projectDir: e.target.value })}
            placeholder="项目目录(可选)— 在你自己的项目里干活" style={inputStyle} />
          {projectDir.trim() && (
            <input value={guardFiles} onChange={(e) => onChange({ guardFiles: e.target.value })}
              placeholder="监控的测试文件(逗号分隔)— agent 改了会警告" style={{ ...inputStyle, height: 30, color: 'var(--text-3)', fontSize: 11.5 }} />
          )}
        </div>
      )}
    </div>
  );
}
