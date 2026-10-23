import { Flex, Spin } from 'antd';

/** Shown while the first route chunk loads. */
export function Loading() {
  return (
    <Flex justify="center" style={{ padding: 48 }}>
      <Spin />
    </Flex>
  );
}
