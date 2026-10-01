/** 共享类型。 */
export interface Msg {
  role: "user" | "assistant";
  content: string;
}
