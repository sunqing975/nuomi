/** 糯米专属（默认专家）表情组件（react-ai-pet：果冻身体 + 17 表情 + 思考特效 + 眼睛跟随光标）。
 *   shape=mochi（米糕）——名字"糯米"正合。mood → expression + reaction 映射。
 *   v0.5：mood 插件情绪（excited/happy/curious/surprised/shy/proud/sad）→ 表情播放后回 idle。 */
import { PetAvatar } from "react-ai-pet";
import type { ExpressionId, ReactionId } from "react-ai-pet";

export type PetMood = "idle" | "thinking" | "typing" | "listening" | Emotion;

/** 后端 mood 插件产出的情绪（RESPONSE_DONE → analyze_emotion） */
export type Emotion = "excited" | "happy" | "curious" | "surprised" | "shy" | "proud" | "sad" | "neutral";

const MOOD_MAP: Record<"idle" | "thinking" | "typing" | "listening", { expression: ExpressionId; reaction: ReactionId | null }> = {
  idle: { expression: "happy", reaction: null },
  thinking: { expression: "curious", reaction: "ponder" },
  typing: { expression: "excited", reaction: null },
  listening: { expression: "surprised", reaction: null },
};

/** 大模型回答情绪 → 表情/反应（回答完播放，随后回 idle） */
export const EMOTION_MAP: Record<Emotion, { expression: ExpressionId; reaction: ReactionId | null }> = {
  excited: { expression: "excited", reaction: "sparkle" },
  happy: { expression: "happy", reaction: null },
  curious: { expression: "curious", reaction: "ponder" },
  surprised: { expression: "surprised", reaction: "shocked" },
  shy: { expression: "shy", reaction: "nuzzle" },
  proud: { expression: "proud", reaction: "nod" },
  sad: { expression: "sad", reaction: "gloom" },
  neutral: { expression: "happy", reaction: null },
};

export default function PetBuddy({
  mood,
  size = 200,
  speech = null,
}: {
  mood: PetMood;
  size?: number;
  speech?: string | null;
}) {
  const cfg =
    mood in MOOD_MAP ? MOOD_MAP[mood as keyof typeof MOOD_MAP] : EMOTION_MAP[mood as Emotion] ?? MOOD_MAP.idle;
  return (
    <div className="pet-buddy">
      <PetAvatar
        shape="mochi"
        color="#e8823a"
        color2="#f7bd78"
        material="jelly"
        expression={cfg.expression}
        reaction={cfg.reaction}
        size={size}
        eyeColor="#3d2b1a"
        eyeShine={0.8}
        eyeGlow={0.12}
        blush={{ strength: 0.45, color: "#ff8d7a" }}
        halo={{ strength: 0.35, color: "#f7bd78", size: 1.2 }}
        inner={{ pattern: "orb", color: "#ffd9a8", strength: 0.3, motion: 0.4 }}
        speech={speech}
      />
    </div>
  );
}
