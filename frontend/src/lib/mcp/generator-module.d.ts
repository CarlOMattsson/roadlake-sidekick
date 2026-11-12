/** Types of the contract type generator (a plain Node ES module, scripts/generate-tool-types.mjs). */
declare module "*/generate-tool-types.mjs" {
  export type ContractTool = {
    name: string;
    inputSchema: unknown;
    outputSchema?: unknown;
  };
  export const CONTRACT_PATH: string;
  export const OUTPUT_PATH: string;
  export const SHAPES_OUTPUT_PATH: string;
  export const REGENERATE_COMMAND: string;
  /** Translates one JSON Schema node to TypeScript source (unformatted). */
  export function schemaToType(
    schema: unknown,
    context: {
      root: unknown;
      shared: Map<string, string>;
      serialized?: boolean;
      asAlias?: boolean;
    },
  ): string;
  /** The formatted TypeScript text for a list of tools. */
  export function generateToolTypes(tools: ContractTool[]): Promise<string>;
  /** The formatted TypeScript text of the runtime shape file for a list of tools. */
  export function generateToolShapeFile(tools: ContractTool[]): Promise<string>;
  export function readContract(path?: string): Promise<ContractTool[]>;
}

/** Types of the shape reducer (scripts/tool-shapes.mjs). */
declare module "*/tool-shapes.mjs" {
  export const SHAPE_TOOLS: string[];
  /** Reduces one JSON Schema node to a runtime shape. */
  export function schemaToShape(schema: unknown): Record<string, unknown>;
  export function shapeConstantName(toolName: string): string;
}
