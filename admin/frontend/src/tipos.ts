export interface Filial {
  codigo: number | string; nome: string;
  razao?: string; cnpj?: string; ie?: string; im?: string; telefone?: string; email?: string;
  rua?: string; numero?: string; complemento?: string; bairro?: string; cidade?: string; uf?: string; cep?: string;
  contato?: string; inativo?: string;
}

export interface Sincronizacao {
  intervalo_min?: number; ultima?: string; proxima?: string; duracao_s?: number;
  inseridas?: number; alteradas?: number; apagadas?: number; carga_inicial?: string; erro?: string;
  ativa?: boolean; pausa?: string; linhas?: number; tabelas?: number;
}

export interface Copia { tabelas: number; linhas: number; atualizada: string | null; bytes: number | null }

export interface InfoAgente {
  modo: string; codempresa: number | string | null; maquina: string; sistema: string;
  sincronizacao: Sincronizacao | null; conectado: string | null;
}

export interface ConsultasDia { dia: string; n: number; erros: number; segundos: number }

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
  filiais_lidas: string | null;
  ip: string;
  agente: InfoAgente;
  copia: Copia | null;
  consultas: { hoje: ConsultasDia | null; dias: ConsultasDia[]; semana: number };
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
