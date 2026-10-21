"""
缠论核心引擎 (Chan Theory Core Engine)

缠论技术分析体系的核心实现，包含：
- 包含关系处理 -> 分型识别 -> 笔 -> 线段 -> 中枢 -> 买卖点
- 逐级递归构建，上一级的输出是下一级的输入
"""

import math
from typing import Optional


# ==============================================================================
# 1. InclusionProcessor - 包含关系处理器
# ==============================================================================
class InclusionProcessor:
    """处理K线包含关系，确保每根独立K线互不包含"""

    def process(self, klines: list[dict]) -> list[dict]:
        """
        处理K线包含关系，返回处理后的K线列表。

        包含关系定义：
        - 当前K线高价>=前高 且 低价<=前低  OR 当前K线高价<=前高 且 低价>=前低
        - 即一根K线完全被另一根K线的价格区间包含

        处理规则：
        - 向上趋势(新高>前高): 取高高、取低高（取两根K线中各自较高的那个）
        - 向下趋势(新低<前低): 取高低、取低低（取两根K线中各自较低的那个）
        - 趋势不明的第一根K线默认按向上处理
        """
        if not klines or len(klines) < 2:
            return klines[:]

        # 深拷贝避免修改原数据
        result = [dict(k) for k in klines]
        processed = [result[0]]  # 第一根K线直接加入
        trend = None  # 方向: None(未定), 'up'(向上), 'down'(向下)

        i = 1
        while i < len(result):
            current = result[i]
            prev = processed[-1]

            # 判断当前K线与前一K线是否存在包含关系
            if self._has_inclusion(current, prev):
                # 确定处理方向
                if trend is None:
                    # 第一对包含关系，用前两根独立K线判断方向
                    if i >= 2:
                        # 找上一个独立K线
                        trend = 'up' if prev['high'] > processed[-2]['high'] else 'down'
                    else:
                        # 不够3根，默认向上
                        trend = 'up'

                # 合并K线
                merged = self._merge_klines(prev, current, trend)
                processed[-1] = merged  # 替换前一K线
                i += 1
            else:
                # 无包含关系，更新趋势方向
                if current['high'] > prev['high']:
                    trend = 'up'
                elif current['low'] < prev['low']:
                    trend = 'down'
                # 否则方向不变

                processed.append(result[i])
                i += 1

        return processed

    def _has_inclusion(self, a: dict, b: dict) -> bool:
        """判断两K线是否有包含关系"""
        return (a['high'] <= b['high'] and a['low'] >= b['low']) or \
               (a['high'] >= b['high'] and a['low'] <= b['low'])

    def _merge_klines(self, prev: dict, current: dict, trend: str) -> dict:
        """按趋势方向合并包含K线"""
        if trend == 'up':
            # 向上: 取高高、取低高
            return {
                'date': current['date'],
                'open': prev['open'],
                'high': max(prev['high'], current['high']),
                'low': max(prev['low'], current['low']),
                'close': current['close'],
                'volume': prev.get('volume', 0) + current.get('volume', 0),
            }
        else:
            # 向下: 取高低、取低低
            return {
                'date': current['date'],
                'open': prev['open'],
                'high': min(prev['high'], current['high']),
                'low': min(prev['low'], current['low']),
                'close': current['close'],
                'volume': prev.get('volume', 0) + current.get('volume', 0),
            }


# ==============================================================================
# 2. FractalIdentifier - 分型识别器
# ==============================================================================
class FractalIdentifier:
    """识别K线序列中的顶分型和底分型"""

    def identify(self, klines: list[dict]) -> dict:
        """
        识别顶分型和底分型。

        顶分型: 3根K线，中间K线的高点是三根中最高的，低点是三根中最高的
        底分型: 3根K线，中间K线的低点是三根中最低的，高点是三根中最低的
        分型间必须交替出现（顶-底-顶-底 或 底-顶-底-顶）

        返回: {'tops': [idx, ...], 'bottoms': [idx, ...]}
        """
        tops = []
        bottoms = []

        if not klines or len(klines) < 3:
            return {'tops': tops, 'bottoms': bottoms}

        n = len(klines)
        raw_tops = []
        raw_bottoms = []

        # 第一步：扫描所有可能的分型位置
        for i in range(1, n - 1):
            left = klines[i - 1]
            mid = klines[i]
            right = klines[i + 1]

            # 顶分型: 中间高点最高，中间低点也最高
            if mid['high'] > left['high'] and mid['high'] > right['high'] and \
               mid['low'] > left['low'] and mid['low'] > right['low']:
                raw_tops.append(i)

            # 底分型: 中间低点最低，中间高点也最低
            if mid['low'] < left['low'] and mid['low'] < right['low'] and \
               mid['high'] < left['high'] and mid['high'] < right['high']:
                raw_bottoms.append(i)

        # 第二步：交替筛选，确保顶底交错
        # 确定第一分型类型
        if not raw_tops and not raw_bottoms:
            return {'tops': tops, 'bottoms': bottoms}

        if not raw_tops:
            tops = raw_tops
            bottoms = raw_bottoms
            return {'tops': tops, 'bottoms': bottoms}

        if not raw_bottoms:
            tops = raw_tops
            bottoms = raw_bottoms
            return {'tops': tops, 'bottoms': bottoms}

        # 两两交替选择
        top_idx = 0
        bottom_idx = 0

        if raw_tops[0] < raw_bottoms[0]:
            # 顶分型先出现
            tops.append(raw_tops[0])
            last_is_top = True
            top_idx = 1
            # 跳过第一个底分型之前的底分型
            while bottom_idx < len(raw_bottoms) and raw_bottoms[bottom_idx] <= raw_tops[0]:
                bottom_idx += 1
        else:
            # 底分型先出现
            bottoms.append(raw_bottoms[0])
            last_is_top = False
            bottom_idx = 1
            # 跳过第一个顶分型之前的顶分型
            while top_idx < len(raw_tops) and raw_tops[top_idx] <= raw_bottoms[0]:
                top_idx += 1

        # 交替添加
        while top_idx < len(raw_tops) and bottom_idx < len(raw_bottoms):
            if last_is_top:
                # 需要一个底分型（在最后一个顶分型之后）
                while bottom_idx < len(raw_bottoms) and raw_bottoms[bottom_idx] <= tops[-1]:
                    bottom_idx += 1
                if bottom_idx < len(raw_bottoms):
                    bottoms.append(raw_bottoms[bottom_idx])
                    last_is_top = False
                    bottom_idx += 1
                else:
                    break
            else:
                # 需要一个顶分型（在最后一个底分型之后）
                while top_idx < len(raw_tops) and raw_tops[top_idx] <= bottoms[-1]:
                    top_idx += 1
                if top_idx < len(raw_tops):
                    tops.append(raw_tops[top_idx])
                    last_is_top = True
                    top_idx += 1
                else:
                    break

        return {'tops': tops, 'bottoms': bottoms}


# ==============================================================================
# 3. StrokeIdentifier - 笔识别器
# ==============================================================================
class StrokeIdentifier:
    """识别连续顶底分型之间的笔"""

    def identify(self, klines: list[dict], fractals: dict) -> list[dict]:
        """
        识别笔：连接相邻的顶分型和底分型。

        规则：
        - 顶底分型之间至少需要5根独立K线（顶分型那根+底分型那根+中间至少3根）
        - 即 |top_idx - bottom_idx| >= 4（相邻索引差至少4）
        - 顶底不能共用K线
        - 一笔向上: 从底分型到顶分型
        - 一笔向下: 从顶分型到底分型

        返回: [{'type': 'up'|'down', 'start': index, 'end': index,
                'start_price', 'end_price'}, ...]
        """
        strokes = []
        tops = fractals.get('tops', [])
        bottoms = fractals.get('bottoms', [])

        if not tops or not bottoms:
            return strokes

        # 合并所有分型并按时间排序，标记类型
        all_fractals = []
        for idx in tops:
            all_fractals.append({'idx': idx, 'type': 'top', 'price': klines[idx]['high']})
        for idx in bottoms:
            all_fractals.append({'idx': idx, 'type': 'bottom', 'price': klines[idx]['low']})
        all_fractals.sort(key=lambda x: x['idx'])

        # 交替筛选：确保类型交替且满足K线间距要求
        valid = []
        for f in all_fractals:
            if not valid:
                valid.append(f)
            elif valid[-1]['type'] != f['type']:
                # 类型交替
                dist = f['idx'] - valid[-1]['idx']
                if dist >= 4:
                    # 满足5根K线要求（首尾+中间至少3根 = 索引差>=4）
                    valid.append(f)
                else:
                    # 不满足间距，选择更优的分型（更高的顶或更低的地）
                    prev_dist = valid[-1]['idx'] - (valid[-2]['idx'] if len(valid) >= 2 else -1)
                    # 保留对笔形态更有利的分型
                    if valid[-1]['type'] == 'top':
                        # 保留更高的顶
                        if f['type'] == 'bottom':
                            # 不能连续两个不同类型，跳过
                            pass
                    # 同类型才会被替换（由交替检查保证到达这里的是不同类型）
                    # 但距离不够，需要替换前一个同类型的
                    # 这里简化处理：如果距离不够，保留较优的
                    if len(valid) >= 2:
                        # 比较当前和前一个同类型谁更优
                        if valid[-1]['type'] == 'top':
                            # 顶分型：谁更高保留谁
                            if f['price'] > valid[-1]['price']:
                                # 但需要确保替换后与前一个分型距离足够
                                if f['idx'] - valid[-2]['idx'] >= 4:
                                    valid[-1] = f
                        else:
                            # 底分型：谁更低保留谁
                            if f['price'] < valid[-1]['price']:
                                if f['idx'] - valid[-2]['idx'] >= 4:
                                    valid[-1] = f

        # 拼接成分型笔
        # 对于每对相邻的（底-顶 或 顶-底），生成一笔
        cleaned = []
        for f in valid:
            if not cleaned:
                cleaned.append(f)
            elif cleaned[-1]['type'] != f['type']:
                if f['idx'] - cleaned[-1]['idx'] >= 4:
                    cleaned.append(f)

        # 从分型生成笔
        for j in range(1, len(cleaned)):
            prev = cleaned[j - 1]
            curr = cleaned[j]

            if prev['type'] == 'bottom' and curr['type'] == 'top':
                # 底->顶：向上笔
                stroke_type = 'up'
                start_price = klines[prev['idx']]['low']
                end_price = klines[curr['idx']]['high']
            elif prev['type'] == 'top' and curr['type'] == 'bottom':
                # 顶->底：向下笔
                stroke_type = 'down'
                start_price = klines[prev['idx']]['high']
                end_price = klines[curr['idx']]['low']
            else:
                continue

            strokes.append({
                'type': stroke_type,
                'start': prev['idx'],
                'end': curr['idx'],
                'start_price': start_price,
                'end_price': end_price,
            })

        return strokes


# ==============================================================================
# 4. SegmentIdentifier - 线段识别器
# ==============================================================================
class SegmentIdentifier:
    """识别线段：由至少3笔组成，用特征序列法处理"""

    def identify(self, strokes: list[dict], klines: list[dict]) -> list[dict]:
        """
        识别线段。

        线段定义：
        - 连续至少3笔，方向交替
        - 向上线段：从向上的笔开始，最终方向向上（起点低，终点高）
        - 向下线段：从向下的笔开始，最终方向向下（起点高，终点低）
        - 线段由奇数笔构成（3,5,7...）

        特征序列法：
        - 向上线段的特征序列 = 其间向下笔的序列
        - 向下线段的特征序列 = 其间向上笔的序列
        - 特征序列出现缺口时，需要反向线段确认

        返回: [{'type': 'up'|'down', 'start': index, 'end': index,
                'start_price', 'end_price', 'strokes': [笔索引]}, ...]
        """
        segments = []

        if not strokes or len(strokes) < 3:
            return segments

        i = 0
        n = len(strokes)

        while i < n:
            # 线段至少需要3笔
            if i + 2 >= n:
                break

            first = strokes[i]
            # 确定线段方向（由第一笔决定）
            direction = first['type']

            # 寻找线段终点：收集奇数笔
            stroke_count = 1
            j = i + 1
            feature_sequence = []  # 特征序列（与线段方向相反的笔）

            while j < n:
                stroke_count += 1
                if strokes[j]['type'] != direction:
                    feature_sequence.append(strokes[j])
                j += 1

                # 至少3笔才能成段
                if stroke_count >= 3 and stroke_count % 2 == 1:
                    # 检查特征序列是否有缺口
                    if self._has_feature_gap(feature_sequence, direction):
                        # 如果有缺口，检查后面是否有反向笔确认
                        if j < n and strokes[j]['type'] == direction:
                            # 有反向笔确认，线段延伸到此处
                            continue
                        else:
                            # 无确认，线段在此结束
                            break
                    else:
                        # 无缺口，检查特征序列分型
                        if len(feature_sequence) >= 2:
                            if self._check_feature_fractal(feature_sequence, direction):
                                # 特征序列出现反向分型，线段结束
                                break

                # 继续收集更多笔
                if j >= n:
                    break

            # 线段终点（最后纳入的笔的索引）
            end_idx = j - 1 if j > i + 2 else i + 2
            # 确保是奇数笔（最后方向与原方向相反）
            num_strokes = end_idx - i + 1
            if num_strokes % 2 == 0:
                end_idx -= 1

            if end_idx - i + 1 >= 3:
                end_stroke = strokes[end_idx]

                segment_start_idx = strokes[i]['start']
                segment_end_idx = end_stroke['end']

                # 确定线段方向和起止价格
                if direction == 'up':
                    seg_type = 'up'
                    start_price = strokes[i]['start_price']
                    end_price = end_stroke['end_price']
                else:
                    seg_type = 'down'
                    start_price = strokes[i]['start_price']
                    end_price = end_stroke['end_price']

                segment_strokes = list(range(i, end_idx + 1))

                segments.append({
                    'type': seg_type,
                    'start': segment_start_idx,
                    'end': segment_end_idx,
                    'start_price': start_price,
                    'end_price': end_price,
                    'direction': direction if seg_type == 'up' else 'down',
                    'strokes': segment_strokes,
                    'high': max(klines[s]['high'] for s in range(segment_start_idx, segment_end_idx + 1)),
                    'low': min(klines[s]['low'] for s in range(segment_start_idx, segment_end_idx + 1)),
                })

                i = end_idx + 1
            else:
                i += 1

        return segments

    def _has_feature_gap(self, feature_seq: list[dict], direction: str) -> bool:
        """检查特征序列是否有缺口"""
        if len(feature_seq) < 2:
            return False
        # 向上线段中，向下特征序列出现低点更高（缺口向上）
        # 向下线段中，向上特征序列出现高点更低（缺口向下）
        if direction == 'up':
            return feature_seq[-1]['start_price'] > feature_seq[-2]['end_price']
        else:
            return feature_seq[-1]['start_price'] < feature_seq[-2]['end_price']

    def _check_feature_fractal(self, feature_seq: list[dict], direction: str) -> bool:
        """检查特征序列是否出现反向分型（至少3个特征序列元素）"""
        if len(feature_seq) < 3:
            return False
        # 向上线段中，向下特征序列出现底分型意味着线段可能结束
        # 向下线段中，向上特征序列出现顶分型意味着线段可能结束
        if direction == 'up':
            # 寻找特征序列的底分型（中间元素低点最低）
            mid = feature_seq[-2]
            left = feature_seq[-3]
            right = feature_seq[-1]
            return mid['end_price'] < left['end_price'] and mid['end_price'] < right['end_price']
        else:
            # 寻找特征序列的顶分型（中间元素高点最高）
            mid = feature_seq[-2]
            left = feature_seq[-3]
            right = feature_seq[-1]
            return mid['end_price'] > left['end_price'] and mid['end_price'] > right['end_price']


# ==============================================================================
# 5. PivotIdentifier - 中枢识别器
# ==============================================================================
class PivotIdentifier:
    """识别中枢：至少3个连续线段重叠的价格区间"""

    def identify(self, segments: list[dict]) -> list[dict]:
        """
        识别中枢。

        中枢定义：
        - 连续至少3段重叠的价格区间
        - ZG（中枢高点）= min(各段高点)
        - ZD（中枢低点）= max(各段低点)
        - ZG > ZD 才有效
        - 中枢延伸：后续段落在这个区间内，中枢继续
        - 中枢扩展：新中枢与旧中枢有重叠，合并

        返回: [{'start_idx', 'end_idx', 'zg', 'zd', 'segments': [段索引]}, ...]
        """
        pivots = []

        if not segments or len(segments) < 3:
            return pivots

        n = len(segments)
        i = 0

        while i < n - 2:
            # 取连续3段
            seg1 = segments[i]
            seg2 = segments[i + 1]
            seg3 = segments[i + 2]

            # 计算重叠区域
            highs = [seg1['high'], seg2['high'], seg3['high']]
            lows = [seg1['low'], seg2['low'], seg3['low']]

            zg = min(highs)  # 中枢高点
            zd = max(lows)   # 中枢低点

            if zg > zd:
                # 有效中枢
                pivot_segs = [i, i + 1, i + 2]
                k = i + 3

                # 中枢延伸：后续段的重叠区域与中枢有交集
                while k < n:
                    seg_k = segments[k]
                    # 判断当前段是否与中枢区间有重叠
                    if seg_k['low'] < zg and seg_k['high'] > zd:
                        pivot_segs.append(k)
                        # 重新计算中枢区间
                        all_highs = [segments[s]['high'] for s in pivot_segs]
                        all_lows = [segments[s]['low'] for s in pivot_segs]
                        zg = min(all_highs)
                        zd = max(all_lows)
                        k += 1
                    else:
                        break

                pivots.append({
                    'start_idx': segments[pivot_segs[0]]['start'],
                    'end_idx': segments[pivot_segs[-1]]['end'],
                    'zg': zg,
                    'zd': zd,
                    'segments': pivot_segs,
                })

                # 检查与上一个中枢是否重叠（中枢扩展）
                if len(pivots) >= 2:
                    prev_pivot = pivots[-2]
                    # 如果两个中枢有重叠，合并
                    if zg < prev_pivot['zd'] and zd > prev_pivot['zg']:
                        # 合并中枢
                        merged_segs = sorted(set(prev_pivot['segments'] + pivot_segs))
                        merged_highs = [segments[s]['high'] for s in merged_segs]
                        merged_lows = [segments[s]['low'] for s in merged_segs]
                        pivots.pop()
                        pivots.pop()
                        pivots.append({
                            'start_idx': segments[merged_segs[0]]['start'],
                            'end_idx': segments[merged_segs[-1]]['end'],
                            'zg': min(merged_highs),
                            'zd': max(merged_lows),
                            'segments': merged_segs,
                        })

                i = pivot_segs[-1]  # 跳过已处理的段
            else:
                i += 1

            i += 1 if i < n - 2 else 0

        return pivots


# ==============================================================================
# 6. TradingSignalIdentifier - 买卖点识别器
# ==============================================================================
class TradingSignalIdentifier:
    """根据中枢和线段识别缠论买卖点"""

    def identify(self, pivots: list[dict], segments: list[dict], klines: list[dict]) -> list[dict]:
        """
        识别缠论三类买卖点。

        一买: 下跌趋势背驰后创出新低，但力度衰竭
             - 特征：新低点的下跌力度小于前一下跌段
        二买: 一买后回调不破前一中枢低点（ZD）
        三买: 向上离开中枢后回调不破中枢高点（ZG）

        一卖/二卖/三卖：对应做空方向

        返回: [{'type': 'buy1'|'buy2'|'buy3'|'sell1'|'sell2'|'sell3',
                'index': K线索引, 'price': 价格, 'pivot_idx': 中枢索引}, ...]
        """
        signals = []

        if not pivots or not segments or not klines:
            return signals

        n_pivots = len(pivots)
        n_segments = len(segments)

        # ---- 一买识别 ----
        # 条件：最后一个中枢之后出现向下的离开段，且力度背驰
        for p_idx, pivot in enumerate(pivots):
            pivot_segs = pivot['segments']
            last_seg_in_pivot = pivot_segs[-1]

            # 中枢之后的离开段
            if last_seg_in_pivot + 1 < n_segments:
                leave_seg = segments[last_seg_in_pivot + 1]
                # 必须是一段向下的离开段（从高位下来）
                if leave_seg['end_price'] < leave_seg['start_price']:
                    # 计算离开段的力度（价格变化幅度 / K线数）
                    leave_power = self._calc_power(leave_seg, klines)

                    # 寻找进入段（中枢形成前的一段）
                    entry_seg = segments[pivot_segs[0] - 1] if pivot_segs[0] > 0 else None
                    if entry_seg and entry_seg['end_price'] < entry_seg['start_price']:
                        entry_power = self._calc_power(entry_seg, klines)
                        # 背驰：离开段力度小于进入段
                        if abs(leave_power) < abs(entry_power):
                            signals.append({
                                'type': 'buy1',
                                'index': leave_seg['end'],
                                'price': klines[leave_seg['end']]['low'],
                                'pivot_idx': p_idx,
                            })

        # ---- 二买识别 ----
        # 条件：一买之后反弹，然后回调不破原中枢低点
        for sig in [s for s in signals if s['type'] == 'buy1']:
            p_idx = sig['pivot_idx']
            if p_idx < len(pivots):
                pivot = pivots[p_idx]
                buy1_idx = sig['index']

                # 在一买之后找回调不破ZD的低点
                for idx in range(buy1_idx + 1, len(klines)):
                    # 简单判断：价格接近但不低于ZD
                    if klines[idx]['low'] >= pivot['zd'] * 0.98 and klines[idx]['low'] <= pivot['zd'] * 1.02:
                        # 确认是局部低点
                        if self._is_local_low(klines, idx):
                            dist_from_buy1 = idx - buy1_idx
                            if dist_from_buy1 >= 3:  # 至少隔3根K线
                                signals.append({
                                    'type': 'buy2',
                                    'index': idx,
                                    'price': klines[idx]['low'],
                                    'pivot_idx': p_idx,
                                })
                                break

        # ---- 三买识别 ----
        # 条件：向上离开中枢后，回调不破ZG
        for p_idx, pivot in enumerate(pivots):
            pivot_segs = pivot['segments']
            last_seg_in_pivot = pivot_segs[-1]

            if last_seg_in_pivot + 1 < n_segments:
                leave_seg = segments[last_seg_in_pivot + 1]
                if leave_seg['end_price'] > leave_seg['start_price']:
                    # 向上离开段，找回调不破ZG的点
                    for idx in range(leave_seg['end'] + 1, len(klines)):
                        if klines[idx]['low'] <= pivot['zg']:
                            break  # 破了ZG就不算三买
                        if klines[idx]['low'] >= pivot['zg'] * 0.99 and self._is_local_low(klines, idx):
                            signals.append({
                                'type': 'buy3',
                                'index': idx,
                                'price': klines[idx]['low'],
                                'pivot_idx': p_idx,
                            })
                            break

        # ---- 一卖识别 ----
        # 条件：最后一个中枢之后出现向上的离开段，且力度背驰
        for p_idx, pivot in enumerate(pivots):
            pivot_segs = pivot['segments']
            last_seg_in_pivot = pivot_segs[-1]

            if last_seg_in_pivot + 1 < n_segments:
                leave_seg = segments[last_seg_in_pivot + 1]
                if leave_seg['end_price'] > leave_seg['start_price']:
                    leave_power = self._calc_power(leave_seg, klines)

                    entry_seg = segments[pivot_segs[0] - 1] if pivot_segs[0] > 0 else None
                    if entry_seg and entry_seg['end_price'] > entry_seg['start_price']:
                        entry_power = self._calc_power(entry_seg, klines)
                        if abs(leave_power) < abs(entry_power):
                            signals.append({
                                'type': 'sell1',
                                'index': leave_seg['end'],
                                'price': klines[leave_seg['end']]['high'],
                                'pivot_idx': p_idx,
                            })

        # ---- 二卖识别 ----
        for sig in [s for s in signals if s['type'] == 'sell1']:
            p_idx = sig['pivot_idx']
            if p_idx < len(pivots):
                pivot = pivots[p_idx]
                sell1_idx = sig['index']

                for idx in range(sell1_idx + 1, len(klines)):
                    if klines[idx]['high'] <= pivot['zg'] * 1.02 and klines[idx]['high'] >= pivot['zg'] * 0.98:
                        if self._is_local_high(klines, idx):
                            if idx - sell1_idx >= 3:
                                signals.append({
                                    'type': 'sell2',
                                    'index': idx,
                                    'price': klines[idx]['high'],
                                    'pivot_idx': p_idx,
                                })
                                break

        # ---- 三卖识别 ----
        for p_idx, pivot in enumerate(pivots):
            pivot_segs = pivot['segments']
            last_seg_in_pivot = pivot_segs[-1]

            if last_seg_in_pivot + 1 < n_segments:
                leave_seg = segments[last_seg_in_pivot + 1]
                if leave_seg['end_price'] < leave_seg['start_price']:
                    for idx in range(leave_seg['end'] + 1, len(klines)):
                        if klines[idx]['high'] >= pivot['zd']:
                            break
                        if klines[idx]['high'] <= pivot['zd'] * 1.01 and self._is_local_high(klines, idx):
                            signals.append({
                                'type': 'sell3',
                                'index': idx,
                                'price': klines[idx]['high'],
                                'pivot_idx': p_idx,
                            })
                            break

        return signals

    def _calc_power(self, segment: dict, klines: list[dict]) -> float:
        """计算线段力度（价格变化 / K线数量）"""
        if segment['end'] <= segment['start']:
            return 0.0
        price_change = segment['end_price'] - segment['start_price']
        bar_count = segment['end'] - segment['start']
        return price_change / bar_count if bar_count > 0 else 0.0

    def _is_local_low(self, klines: list[dict], idx: int, window: int = 2) -> bool:
        """判断是否为局部低点"""
        if idx < window or idx >= len(klines) - window:
            return False
        current_low = klines[idx]['low']
        for i in range(1, window + 1):
            if klines[idx - i]['low'] <= current_low or klines[idx + i]['low'] <= current_low:
                return False
        return True

    def _is_local_high(self, klines: list[dict], idx: int, window: int = 2) -> bool:
        """判断是否为局部高点"""
        if idx < window or idx >= len(klines) - window:
            return False
        current_high = klines[idx]['high']
        for i in range(1, window + 1):
            if klines[idx - i]['high'] >= current_high or klines[idx + i]['high'] >= current_high:
                return False
        return True


# ==============================================================================
# 7. ChanEngine - 主入口
# ==============================================================================
class ChanEngine:
    """缠论多维技术分析引擎主入口"""

    def __init__(self):
        self.inclusion = InclusionProcessor()
        self.fractal = FractalIdentifier()
        self.stroke = StrokeIdentifier()
        self.segment = SegmentIdentifier()
        self.pivot = PivotIdentifier()
        self.signal = TradingSignalIdentifier()

    def analyze(self, df) -> dict:
        """
        对DataFrame执行完整缠论分析。

        输入: pandas DataFrame (columns: date, open, high, low, close, volume)
        输出: {
            'signal': float (-1.0 到 1.0，正=买入，负=卖出),
            'confidence': float (0.0 到 1.0),
            'details': {
                'strokes': [...],
                'segments': [...],
                'pivots': [...],
                'trading_points': [...],
                'trend': 'up'|'down'|'sideways'
            }
        }
        """
        # 输入验证
        if df is None or df.empty:
            return self._empty_result()

        required_cols = ['date', 'open', 'high', 'low', 'close']
        for col in required_cols:
            if col not in df.columns:
                return self._empty_result()

        # DataFrame 转 K线字典列表
        klines = []
        for _, row in df.iterrows():
            kline = {
                'date': str(row['date']),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row.get('volume', 0)),
            }
            klines.append(kline)

        if len(klines) < 5:
            return self._empty_result()

        # Step 1: 包含关系处理
        processed_klines = self.inclusion.process(klines)

        # Step 2: 分型识别
        fractals = self.fractal.identify(processed_klines)

        # Step 3: 笔识别
        strokes = self.stroke.identify(processed_klines, fractals)

        # Step 4: 线段识别
        segments = self.segment.identify(strokes, processed_klines)

        # Step 5: 中枢识别
        pivots = self.pivot.identify(segments)

        # Step 6: 买卖点识别
        trading_points = self.signal.identify(pivots, segments, processed_klines)

        # Step 7: 计算综合信号
        signal, confidence = self._calculate_signal(trading_points, processed_klines)

        # Step 8: 判断趋势
        trend = self._determine_trend(strokes, segments, processed_klines)

        return {
            'signal': signal,
            'confidence': confidence,
            'details': {
                'strokes': self._serialize_strokes(strokes),
                'segments': self._serialize_segments(segments),
                'pivots': self._serialize_pivots(pivots),
                'trading_points': self._serialize_trading_points(trading_points),
                'trend': trend,
            },
        }

    def _calculate_signal(self, trading_points: list[dict], klines: list[dict]) -> tuple:
        """
        根据买卖点计算综合信号。

        权重：
        - 一买/一卖: ±0.6 ~ ±1.0
        - 二买/二卖: ±0.3 ~ ±0.6
        - 三买/三卖: ±0.1 ~ ±0.3

        买卖点同时存在时互相抵消。
        最近出现的点权重更高。
        """
        if not trading_points:
            return 0.0, 0.0

        # 对信号排序（按时间，越近越靠后）
        sorted_points = sorted(trading_points, key=lambda x: x['index'])

        buy_signals = []
        sell_signals = []

        for sp in sorted_points:
            t = sp['type']
            if t == 'buy1':
                buy_signals.append(0.8)
            elif t == 'buy2':
                buy_signals.append(0.45)
            elif t == 'buy3':
                buy_signals.append(0.2)
            elif t == 'sell1':
                sell_signals.append(-0.8)
            elif t == 'sell2':
                sell_signals.append(-0.45)
            elif t == 'sell3':
                sell_signals.append(-0.2)

        # 时间衰减：越近的信号权重越高
        if klines and sorted_points:
            last_idx = len(klines) - 1
            weighted_buy = 0.0
            weighted_sell = 0.0
            total_weight = 0.0

            for sp, raw in zip(sorted_points, buy_signals + sell_signals):
                # 距离越近权重越高
                distance = max(1, last_idx - sp['index'])
                weight = 1.0 / math.sqrt(distance)
                total_weight += weight

                if raw > 0:
                    weighted_buy += raw * weight
                else:
                    weighted_sell += abs(raw) * weight  # sell是负数

            if total_weight > 0:
                net = (weighted_buy - weighted_sell) / total_weight
            else:
                net = 0.0
        else:
            # 简单平均
            all_values = buy_signals + sell_signals
            net = sum(all_values) / len(all_values) if all_values else 0.0

        # 信号裁剪到[-1, 1]
        signal = max(-1.0, min(1.0, net))

        # 置信度：基于买卖点数量和一致性
        all_signals = buy_signals + sell_signals
        if not all_signals:
            confidence = 0.0
        else:
            # 多信号同向 = 高置信度
            positive_count = len(buy_signals)
            negative_count = len(sell_signals)
            total_count = positive_count + negative_count

            if total_count == 0:
                confidence = 0.0
            else:
                # 方向一致性
                consistency = abs(positive_count - negative_count) / total_count
                # 信号数量贡献
                quantity_bonus = min(1.0, total_count / 5.0) * 0.3
                # 高权重信号贡献
                has_strong = any(t['type'] in ('buy1', 'sell1') for t in trading_points)
                strong_bonus = 0.3 if has_strong else 0.0
                confidence = min(1.0, consistency * 0.4 + quantity_bonus + strong_bonus)

        return round(signal, 4), round(confidence, 4)

    def _determine_trend(self, strokes: list[dict], segments: list[dict], klines: list[dict]) -> str:
        """判断当前趋势方向"""
        if not klines:
            return 'sideways'

        n = len(klines)

        # 基于最近几笔的方向
        if strokes:
            recent_strokes = strokes[-3:]  # 最近3笔
            up_count = sum(1 for s in recent_strokes if s['type'] == 'up')
            down_count = sum(1 for s in recent_strokes if s['type'] == 'down')

            # 同时参考线段
            if segments:
                recent_segments = segments[-2:]  # 最近2段
                seg_up = sum(1 for s in recent_segments if s['end_price'] > s['start_price'])
                seg_down = len(recent_segments) - seg_up

                up_count += seg_up
                down_count += seg_down

            if up_count > down_count * 1.5:
                return 'up'
            elif down_count > up_count * 1.5:
                return 'down'

        # 基于价格相对位置
        if n >= 20:
            recent_20 = klines[-20:]
            avg = sum(k['close'] for k in recent_20) / len(recent_20)
            current = klines[-1]['close']
            if current > avg * 1.03:
                return 'up'
            elif current < avg * 0.97:
                return 'down'

        return 'sideways'

    def _serialize_strokes(self, strokes: list[dict]) -> list[dict]:
        """序列化笔列表"""
        result = []
        for s in strokes:
            result.append({
                'type': s['type'],
                'start': int(s['start']),
                'end': int(s['end']),
                'start_price': round(float(s['start_price']), 4),
                'end_price': round(float(s['end_price']), 4),
            })
        return result

    def _serialize_segments(self, segments: list[dict]) -> list[dict]:
        """序列化线段列表"""
        result = []
        for s in segments:
            result.append({
                'type': s['type'],
                'start': int(s['start']),
                'end': int(s['end']),
                'start_price': round(float(s['start_price']), 4),
                'end_price': round(float(s['end_price']), 4),
                'strokes': [int(x) for x in s.get('strokes', [])],
                'high': round(float(s.get('high', 0)), 4),
                'low': round(float(s.get('low', 0)), 4),
            })
        return result

    def _serialize_pivots(self, pivots: list[dict]) -> list[dict]:
        """序列化中枢列表"""
        result = []
        for p in pivots:
            result.append({
                'start_idx': int(p['start_idx']),
                'end_idx': int(p['end_idx']),
                'zg': round(float(p['zg']), 4),
                'zd': round(float(p['zd']), 4),
                'segments': [int(x) for x in p.get('segments', [])],
            })
        return result

    def _serialize_trading_points(self, points: list[dict]) -> list[dict]:
        """序列化买卖点列表"""
        result = []
        for pt in points:
            result.append({
                'type': pt['type'],
                'index': int(pt['index']),
                'price': round(float(pt['price']), 4),
                'pivot_idx': int(pt.get('pivot_idx', -1)),
            })
        return result

    def _empty_result(self) -> dict:
        """返回空结果"""
        return {
            'signal': 0.0,
            'confidence': 0.0,
            'details': {
                'strokes': [],
                'segments': [],
                'pivots': [],
                'trading_points': [],
                'trend': 'sideways',
            },
        }
