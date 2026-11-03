export interface Filial { codigo: number | string; nome: string }

export interface Empresa {
  id: string;
  nome: string;
  ativa: number | boolean;
  criada: string | null;
  tem_chave: number | boolean;
  online: boolean;
  visto: string | null;
  versao: string;
  banco: string;
  filiais: Filial[] | null;
  filiais_erro: string;
  filiais_pedidas: boolean;
}

export interface Usuario {
  id: number;
  login: string;
  nome: string;
  admin: number | boolean;
  ativo: number | boolean;
  modulos: string[];
  empresa_id: string | null;
  ultimo_acesso: string | null;
  trocar_senha: number | boolean;
  super: boolean;
}

export type Modulos = Record<string, string>;

export interface Aviso { id: number; texto: string; tipo: "erro" | "atencao" }
