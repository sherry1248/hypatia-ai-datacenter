import { copyFile, mkdir } from 'node:fs/promises';
import { accessSync, constants } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDirectory = resolve(scriptDirectory, '..');
const destinationDirectory = resolve(frontendDirectory, 'public', 'data');
const fileNames = ['node_positions.csv', 'network_costs.csv', 'routing_events.csv', 'placement_results.csv'];

try {
  await mkdir(destinationDirectory, { recursive: true });
  for (const fileName of fileNames) {
    const source = resolve(frontendDirectory, '..', 'satgenpy', 'demo_data', fileName);
    const destination = resolve(destinationDirectory, fileName);
    try {
      accessSync(source, constants.R_OK);
    } catch {
      throw new Error(`데모 데이터 원본을 찾을 수 없습니다: ${source}`);
    }
    await copyFile(source, destination);
    console.log(`데모 데이터를 복사했습니다: ${source} -> ${destination}`);
  }
} catch (error) {
  console.error(`데모 데이터 복사에 실패했습니다: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}
