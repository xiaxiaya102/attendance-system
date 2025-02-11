import os
from datetime import datetime, timedelta
import pandas as pd
from flask import Flask, render_template, request, session, redirect, url_for, Blueprint
from werkzeug.utils import secure_filename
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
app.config['UPLOAD_FOLDER'] = 'uploads'

# 配置代理设置
app.config['PREFERRED_URL_SCHEME'] = 'http'
app.config['SERVER_NAME'] = None

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 修改session配置
app.secret_key = os.urandom(24)

# 添加代理中间件
class ScriptNameMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]
        return self.app(environ, start_response)

app.wsgi_app = ScriptNameMiddleware(app.wsgi_app)

# 创建蓝图，不设置 url_prefix
bp = Blueprint('attendance', __name__)

def parse_datetime(date_str, time_str):
    """解析日期和时间"""
    try:
        # 处理日期中包含星期的情况
        if isinstance(date_str, str) and '星期' in date_str:
            date_str = date_str.split('星期')[0].strip()
        
        # 解析日期
        date = pd.to_datetime(date_str).date()
        
        # 解析时间
        time = pd.to_datetime(time_str).time()
        
        return date, time
    except Exception as e:
        print(f"Error parsing datetime: date_str={date_str}, time_str={time_str}, error={e}")
        return None, None

def calculate_overtime_and_allowance(row, df, is_dormitory=False):
    try:
        date_str = row['日期']
        time_str = row['实际打卡时间']
        
        if pd.isna(date_str) or pd.isna(time_str):
            return pd.Series({'加班时长': 0, '餐补': 0, '交通补贴': 0})
        
        # 解析日期和时间
        date, time = parse_datetime(date_str, time_str)
        if date is None or time is None:
            return pd.Series({'加班时长': 0, '餐补': 0, '交通补贴': 0})
            
        datetime_combined = datetime.combine(date, time)
        
        # 判断是否为工作日和周五
        weekday = date.weekday()  # 0-4 表示周一至周五，5-6 表示周六日
        is_workday = weekday < 5
        is_friday = weekday == 4
        
        # 获取当天该员工的所有打卡记录
        day_records = df[(df['姓名'] == row['姓名']) & 
                        (pd.to_datetime(df['日期'].apply(lambda x: x.split('星期')[0].strip() if isinstance(x, str) else x)).dt.date == date)]
        
        overtime = 0
        meal_allowance = 0
        transport_allowance = 0
        
        if is_workday:
            # 工作日加班计算
            if time >= datetime.strptime('18:00', '%H:%M').time():
                end_time = datetime_combined
                start_time = datetime.combine(date, datetime.strptime('18:30', '%H:%M').time())
                overtime = (end_time - start_time).total_seconds() / 3600
                
                # 每天扣除0.5小时无效时间
                overtime = max(0, int(overtime - 0.5))
                
                # 计算补贴
                # 获取当天该员工的所有晚上加班记录
                evening_records = day_records[
                    pd.to_datetime(day_records['实际打卡时间']).dt.time >= datetime.strptime('18:00', '%H:%M').time()
                ]
                
                if not evening_records.empty:
                    latest_time = pd.to_datetime(evening_records['实际打卡时间']).max().time()
                    
                    # 周五特殊处理：一定会到18点，所以至少有一次餐补
                    if is_friday:
                        meal_allowance += 10  # 第一次餐补
                        # 如果超过21点，给第二次餐补
                        if latest_time >= datetime.strptime('21:00', '%H:%M').time():
                            meal_allowance += 10
                    else:
                        # 其他工作日按正常规则
                        # 如果加班到20点后，给第一次餐补
                        if latest_time >= datetime.strptime('20:00', '%H:%M').time():
                            meal_allowance += 10
                        # 如果加班到21点后，给第二次餐补
                        if latest_time >= datetime.strptime('21:00', '%H:%M').time():
                            meal_allowance += 10
                    
                    # 21点后给交通补贴（非寝室）
                    if latest_time >= datetime.strptime('21:00', '%H:%M').time() and not is_dormitory:
                        transport_allowance = 10
                
                return pd.Series({
                    '加班时长': round(overtime, 2),
                    '餐补': meal_allowance,
                    '交通补贴': transport_allowance
                })
        else:
            # 休息日加班计算
            if not day_records.empty:
                day_records['打卡时间'] = pd.to_datetime(day_records['实际打卡时间'])
                first_record = day_records['打卡时间'].min()
                last_record = day_records['打卡时间'].max()
                
                # 只在最早的打卡记录上计算整天的加班时间和补贴
                current_record_time = pd.to_datetime(time_str)
                if current_record_time == first_record:
                    if pd.notna(first_record) and pd.notna(last_record):
                        overtime = (last_record - first_record).total_seconds() / 3600
                        overtime = max(0, overtime - 0.5)
                        
                        # 休息日加班超过4小时给第一次餐补
                        if overtime >= 4:
                            meal_allowance += 10
                            
                        # 休息日加班超过8小时给第二次餐补
                        if overtime >= 8:
                            meal_allowance += 10
                            
                        # 如果加班到21点后，给交通补贴（非寝室）
                        last_time = last_record.time()
                        if last_time >= datetime.strptime('21:00', '%H:%M').time() and not is_dormitory:
                            transport_allowance = 10
                            
                        print(f"休息日 {date_str} 打卡时间: {first_record.time()} - {last_record.time()}, "
                              f"加班时长: {overtime:.2f}小时, 餐补: {meal_allowance}元, 交通补贴: {transport_allowance}元")
                        
                        return pd.Series({
                            '加班时长': round(overtime, 2),
                            '餐补': meal_allowance,
                            '交通补贴': transport_allowance
                        })
        
        return pd.Series({'加班时长': 0, '餐补': 0, '交通补贴': 0})
                
    except Exception as e:
        print(f"计算加班时间出错: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return pd.Series({'加班时长': 0, '餐补': 0, '交通补贴': 0})

def process_excel(file_path, is_dormitory=False):
    try:
        print(f"\n开始处理Excel文件: {file_path}")
        print(f"住寝室设置: {'是' if is_dormitory else '否'}")
        
        # 读取Excel文件的第二个sheet，从第三行开始（表头）
        try:
            df = pd.read_excel(file_path, sheet_name=1, header=2)
            print(f"成功读取Excel文件，共{len(df)}行数据")
            print(f"列名: {list(df.columns)}")  # 打印列名
        except Exception as e:
            print(f"读取Excel文件失败: {str(e)}")
            return None
            
        # 检查必需的列是否存在
        required_columns = ['日期', '姓名', '部门', '实际打卡时间']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            print(f"Excel文件缺少必需的列: {missing_columns}")
            return None
            
        # 计算每行的加班时间和补贴
        try:
            result = df.apply(lambda row: calculate_overtime_and_allowance(row, df, is_dormitory), axis=1)
            df['加班时长'] = result['加班时长']
            df['餐补'] = result['餐补']
            df['交通补贴'] = result['交通补贴']
        except Exception as e:
            print(f"计算加班时间和补贴失败: {str(e)}")
            return None
        
        # 按日期和人员分组，计算每天的加班时长和补贴
        try:
            daily_overtime = df.groupby(['日期', '姓名']).agg({
                '加班时长': 'sum',
                '餐补': 'max',  # 每天最多两次餐补
                '交通补贴': 'max'  # 每天最多一次交通补贴
            }).reset_index()
            print(f"成功计算每日加班明细，共{len(daily_overtime)}条记录")
        except Exception as e:
            print(f"计算每日加班明细失败: {str(e)}")
            return None
        
        # 按人员分组并汇总
        try:
            summary = df.groupby(['姓名']).agg({
                '加班时长': 'sum',
                '餐补': 'sum',
                '交通补贴': 'sum',
                '日期': 'count'  # 计算打卡次数
            }).reset_index()
            
            # 将打卡次数除以2得到实际打卡天数
            summary.columns = ['姓名', '总加班时长', '总餐补', '总交通补贴', '打卡次数']
            summary['打卡天数'] = (summary['打卡次数'] / 2).astype(int)
            
            # 计算每日平均工时和平均加班时长
            summary['每日平均工时'] = (8 + summary['总加班时长'] / summary['打卡天数']).round(2)
            summary['每日平均加班时长'] = (summary['总加班时长'] / summary['打卡天数']).round(2)
            
            print(f"成功计算汇总数据，共{len(summary)}人")
        except Exception as e:
            print(f"计算汇总数据失败: {str(e)}")
            return None
        
        # 重新排列列的顺序
        summary = summary[[
            '姓名', '总加班时长', '每日平均工时', '每日平均加班时长',
            '总餐补', '总交通补贴', '打卡天数', '打卡次数'
        ]]
        
        # 打印日志
        print("\n========== 每日加班补贴详情 ==========")
        for _, row in daily_overtime.iterrows():
            date_str = row['日期']
            if isinstance(date_str, str) and '星期' in date_str:
                print(f"{date_str}: {row['姓名']} 加班 {row['加班时长']:.2f} 小时, "
                      f"餐补 {row['餐补']}元, 交通补贴 {row['交通补贴']}元")
        
        print("\n========== 总计汇总 ==========")
        for _, row in summary.iterrows():
            print(f"{row['姓名']}: 总计加班 {row['总加班时长']:.2f} 小时, "
                  f"每日平均工时 {row['每日平均工时']:.2f} 小时, "
                  f"每日平均加班时长 {row['每日平均加班时长']:.2f} 小时, "
                  f"总餐补 {row['总餐补']}元, 总交通补贴 {row['总交通补贴']}元, "
                  f"打卡天数: {row['打卡天数']} 天, 打卡次数: {row['打卡次数']} 次")
        
        # 转换数据为字典格式，确保数值类型正确
        try:
            summary_dict = summary.to_dict('records')
            for item in summary_dict:
                item['总加班时长'] = float(item['总加班时长'])
                item['每日平均工时'] = float(item['每日平均工时'])
                item['每日平均加班时长'] = float(item['每日平均加班时长'])
                item['总餐补'] = int(item['总餐补'])
                item['总交通补贴'] = int(item['总交通补贴'])
                item['打卡天数'] = int(item['打卡天数'])
                item['打卡次数'] = int(item['打卡次数'])
            
            daily_details = daily_overtime.to_dict('records')
            
            # 准备返回数据
            result_data = {
                'summary': summary_dict,
                'daily_details': daily_details,
                'is_dormitory': is_dormitory
            }
            print("数据处理完成，准备返回结果")
            return result_data
            
        except Exception as e:
            print(f"转换结果数据失败: {str(e)}")
            return None
        
    except Exception as e:
        print(f"处理Excel文件出错: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/upload', methods=['POST'])
def upload():
    print("\n========== 开始处理上传请求 ==========")
    if 'file' not in request.files:
        print("错误：未找到上传的文件")
        return render_template('index.html', error='请选择文件')
    
    file = request.files['file']
    if file.filename == '':
        print("错误：文件名为空")
        return render_template('index.html', error='请选择文件')
    
    if file and file.filename.endswith('.xlsx'):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        print(f"文件已保存到: {file_path}")
        
        # 获取寝室设置
        is_dormitory = request.form.get('is_dormitory') == 'on'
        print(f"寝室设置: {'是' if is_dormitory else '否'}")
        
        # 处理Excel文件
        result_data = process_excel(file_path, is_dormitory)
        if result_data:
            print("Excel处理成功，保存结果到session")
            session['results'] = result_data
            print("准备重定向到results页面")
            return redirect(url_for('attendance.results'))
        
        print("Excel处理失败")
        return render_template('index.html', error='文件格式错误。请从企业微信"考勤汇总"导出Excel文件，确保包含：日期、姓名、部门、实际打卡时间等字段。')
    
    print("文件格式不正确")
    return render_template('index.html', error='请上传企业微信导出的考勤汇总Excel文件（.xlsx格式）')

@bp.route('/results')
def results():
    print("\n========== 进入results路由 ==========")
    results = session.get('results')
    print(f"从session获取到的results: {results is not None}")
    
    if not results:
        print("未找到results数据，重定向到首页")
        return redirect(url_for('attendance.index'))
    
    # 确保数据格式正确
    try:
        summary = results.get('summary', [])
        print(f"汇总数据条数: {len(summary)}")
        
        # 确保所有必需的字段都存在
        required_fields = ['姓名', '总加班时长', '每日平均工时', '每日平均加班时长', 
                         '总餐补', '总交通补贴', '打卡天数', '打卡次数']
        
        for row in summary:
            missing_fields = [field for field in required_fields if field not in row]
            if missing_fields:
                print(f"数据缺少必需字段: {missing_fields}")
                return redirect(url_for('attendance.index'))
        
        print("数据验证通过，准备渲染模板")
        return render_template('index.html', results=results)
    except Exception as e:
        print(f"处理results数据时出错: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return redirect(url_for('attendance.index'))

# 注册蓝图
app.register_blueprint(bp)

# 添加根路径重定向
@app.route('/')
def root():
    return redirect(url_for('attendance.index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False) 