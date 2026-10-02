/** ui-wizard/WelcomeWizard：首次运行向导（阶段 D）。
 *  全新环境（未配置任何 LLM 供应商/模型）时全屏展示：
 *  步骤1 欢迎 + 工作区路径（默认 ~/Documents/Nuomi，可改，写入 settings）
 *  步骤2 LLM 供应商配置（OpenAI 兼容：名称/地址/Key/模型）→ 保存并激活。
 *  完成后进入应用主界面。 */
import { useState } from "react";
import { activateModel, addCustomProvider, saveBootstrapWorkspace } from "../../api";
import { t as tr } from "../../i18n";

export default function WelcomeWizard({
  workspace,
  onFinished,
  onError,
}: {
  workspace: string;
  onFinished: () => void;
  onError: (msg: string) => void;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [ws, setWs] = useState(workspace);
  const [name, setName] = useState("DeepSeek");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [apiKey, setApiKey] = useState("");
  const [modelId, setModelId] = useState("deepseek-chat");
  const [busy, setBusy] = useState(false);

  const next = () => {
    if (!ws.trim()) {
      onError(tr("wizard.workspaceRequired"));
      return;
    }
    setStep(2);
  };

  const finish = async () => {
    setBusy(true);
    try {
      await saveBootstrapWorkspace(ws.trim());
      const mid = modelId.trim() || "deepseek-chat";
      const resp = await addCustomProvider({
        name: name.trim() || "DeepSeek",
        base_url: baseUrl.trim() || "https://api.deepseek.com",
        protocol: "openai",
        api_key: apiKey.trim(),
        models: [{ id: mid, label: mid, efforts: ["medium"] }],
      });
      const prov = resp.providers.find((p) => p.label === (name.trim() || "DeepSeek"));
      if (prov) {
        await activateModel(prov.key, mid);
      }
      onFinished();
    } catch (e) {
      onError(String(e instanceof Error ? e.message : e));
      setBusy(false);
    }
  };

  return (
    <div className="wizard-mask">
      <div className="wizard-card">
        <div className="wizard-brand">
          <span className="wizard-logo">🍡</span>
          <span className="wizard-title">{tr("wizard.title")}</span>
          <span className="wizard-sub">{tr("wizard.subtitle")}</span>
        </div>

        {step === 1 ? (
          <div className="wizard-body">
            <div className="wizard-step-title">{tr("wizard.workspaceLabel")}</div>
            <div className="wizard-desc">{tr("wizard.workspaceDesc")}</div>
            <label className="wizard-field">
              <span className="wizard-field-label">{tr("wizard.workspacePath")}</span>
              <input
                className="wizard-input mono"
                value={ws}
                onChange={(e) => setWs(e.target.value)}
                placeholder={tr("wizard.workspacePlaceholder")}
              />
            </label>
            <button className="wizard-primary" onClick={next}>
              {tr("wizard.next")}
            </button>
          </div>
        ) : (
          <div className="wizard-body">
            <div className="wizard-step-title">{tr("wizard.llmTitle")}</div>
            <div className="wizard-desc">{tr("wizard.llmDesc")}</div>
            <label className="wizard-field">
              <span className="wizard-field-label">{tr("wizard.providerName")}</span>
              <input className="wizard-input" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="wizard-field">
              <span className="wizard-field-label">{tr("wizard.baseUrl")}</span>
              <input className="wizard-input mono" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </label>
            <label className="wizard-field">
              <span className="wizard-field-label">{tr("wizard.apiKey")}</span>
              <input
                className="wizard-input mono"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={tr("wizard.apiKeyPlaceholder")}
              />
            </label>
            <label className="wizard-field">
              <span className="wizard-field-label">{tr("wizard.modelId")}</span>
              <input className="wizard-input mono" value={modelId} onChange={(e) => setModelId(e.target.value)} />
            </label>
            <div className="wizard-actions">
              <button className="wizard-ghost" onClick={() => setStep(1)} disabled={busy}>
                {tr("common.back")}
              </button>
              <button className="wizard-primary" onClick={finish} disabled={busy}>
                {busy ? tr("wizard.busy") : tr("wizard.finish")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
