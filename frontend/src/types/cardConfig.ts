/** 函数参数定义 */
export interface ParamDef {
  name: string;
  type: 'string' | 'number' | 'boolean';
  required: boolean;
  description: string;
}

/** 单个函数定义 */
export interface FuncDef {
  type: 'inline_python';
  name: string;
  description: string;
  result_type: 'card' | 'text';
  card_type: string;
  parameters: ParamDef[];
  code: string;
}

/** 卡片配置顶层结构（存储在 Skill.metadata.card_config） */
export interface CardConfig {
  enabled: boolean;
  functions: FuncDef[];
}
