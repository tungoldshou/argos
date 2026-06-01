// Markdown.tsx — 渲染 agent 答复的 markdown(标题/列表/表格/代码高亮/行内代码)。
// react-markdown 默认不渲染裸 HTML(不挂 rehype-raw) → 天然防 XSS。
// 代码块定制:语言标签 + 一键复制。
import { useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';

function CodeBlock({ className, children }: { className?: string; children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const lang = /language-(\w+)/.exec(className ?? '')?.[1] ?? 'text';
  const code = String(children ?? '');
  const copy = () => {
    navigator.clipboard?.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <div style={{ position: 'relative', margin: '10px 0', borderRadius: 10, overflow: 'hidden', border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.02))' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '5px 10px', borderBottom: '1px solid var(--border)', fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--text-3)' }}>
        <span>{lang}</span>
        <button onClick={copy} style={{ background: 'none', border: 'none', color: copied ? 'var(--live, #45e0a0)' : 'var(--text-3)', cursor: 'pointer', fontFamily: 'var(--mono)', fontSize: 10.5 }}>
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre style={{ margin: 0, padding: '11px 13px', overflow: 'auto', fontFamily: 'var(--mono)', fontSize: 12.5, lineHeight: 1.55 }}>
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md-body" style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--text-1)' }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          code({ className, children, ...props }) {
            const isBlock = /language-/.test(className ?? '') || String(children).includes('\n');
            if (isBlock) return <CodeBlock className={className}>{children}</CodeBlock>;
            return (
              <code style={{ fontFamily: 'var(--mono)', fontSize: 12, background: 'var(--surface-2, rgba(255,255,255,.05))', padding: '1px 5px', borderRadius: 4 }} {...props}>
                {children}
              </code>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
