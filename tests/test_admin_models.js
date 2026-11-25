const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../api/admin/static/app.js'), 'utf8');
const functions = source.slice(source.indexOf('function modelOptions('), source.indexOf('function renderModels('));

function setup() {
  const state = {data: {
    agents: [{id: 1, output_modality: 'audio'}, {id: 2, output_modality: 'image'}, {id: 3, output_modality: 'text'}],
    models: [
      {id: 4, model_ids: [4, 9], name: 'Voice', openrouter_id: 'test/voice', output_modalities: ['audio']},
      {id: 5, name: 'Vision', openrouter_id: 'test/vision', output_modalities: ['text']},
      {id: 6, name: 'Image', openrouter_id: 'test/image', output_modalities: ['image']},
      {id: 7, name: 'Unknown', openrouter_id: 'test/unknown', output_modalities: []},
      {id: 8, name: 'Duplicate', openrouter_id: 'test/voice', output_modalities: ['audio']},
    ],
  }};
  const context = vm.createContext({state});
  vm.runInContext(functions, context);
  return context;
}

test('filters outputs, deduplicates provider IDs and preserves selected legacy ID', () => {
  const context = setup();
  const options = context.modelOptions(1, 9);
  assert.equal(options.length, 2); // placeholder + one audio model
  assert.equal(options[1].id, 9);
  assert.equal(context.modelOptions(2)[1].id, 6);
  assert.equal(context.modelOptions(3)[1].id, 5);
});

test('changing the override agent replaces the dropdown with compatible models', () => {
  const context = setup();
  const model = {value: '9'};
  context.$ = id => id === '#model_id' ? model : {value: '2'};
  context.select = (id, options, value, extra) => JSON.stringify({id, options, value, extra});
  context.refreshOverrideModels();
  const result = JSON.parse(model.outerHTML);
  assert.equal(result.options.length, 2);
  assert.equal(result.options[1].id, 6);
  assert.equal(result.extra, 'required');
  assert.ok(!result.options.some(option => option.id === 9));
});

test('unavailable capabilities leave only the empty placeholder', () => {
  const context = setup();
  context.state.data.agents.push({id: 4, output_modality: 'video'});
  const options = context.modelOptions(4);
  assert.equal(options.length, 1);
  assert.equal(options[0].id, '');
  assert.match(options[0].name, /Nenhum modelo/);
});
